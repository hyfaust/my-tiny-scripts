#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LaTeX Derivative Notation Transformer

Convert Leibniz derivative notation in LaTeX formulas to Lagrange or Newton notation.
Supports both ordinary and partial derivatives.

Usage:
    python latex_deriv.py -t lagrange "\frac{d}{dx}f(x)"
    python latex_deriv.py -t newton "\frac{d^2}{dt^2}y(t)"
    echo "\frac{d}{dx}f(x)" | python latex_deriv.py -t lagrange
    python latex_deriv.py -t lagrange -o output.tex input.tex
    python latex_deriv.py -t newton -s -r "\frac{d^2}{dt^2}y(t)"  # 简化 + 去除幂次括号
"""

import re
import sys
import argparse
import warnings
from typing import Optional, Tuple, List, Union


# ──────────────────────────────────────────────────────────
# Regular Expressions for Matching Leibniz Derivatives
# ──────────────────────────────────────────────────────────

# Ordinary derivative: \frac{d^order}{dvar^order}func(args)
ORDINARY_RE = re.compile(
    r'\\frac\{d(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\}\{d([a-zA-Z]+)(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\}\s*'
    r'((?:\\?)(?:[a-zA-Z]+))\s*(?:\(([^)]*)\)|\{\s*\\left\(\s*([^)]*?)\s*\\right\)\s*\})?',
    re.DOTALL
)

# Partial derivative: \frac{\partial^order}{\partial var^order ...}func(args)
PARTIAL_RE = re.compile(
    r'\\frac\{\s*\\partial(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\}\{\s*\\partial\s+([a-zA-Z]+)(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\s*'
    r'(?:\\partial\s+([a-zA-Z]+)(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\s*)?\}\s*(\\?[a-zA-Z]+)(?:\(([^)]*)\))?',
    re.DOTALL
)

# Alternative partial pattern for multiple variables in denominator
# e.g. \frac{\partial^2}{\partial x \partial y}f(x,y)
PARTIAL_MULTI_RE = re.compile(
    r'\\frac\{\s*\\partial(?:\^(\d+|[a-zA-Z]+|\{[^}]+\}))?\}\{((?:\s*\\partial\s+[a-zA-Z]+(?:\^(?:\d+|[a-zA-Z]+|\{[^}]+\}))?\s*)+)'
    r'\}\s*(\\?[a-zA-Z]+)(?:\(([^)]*)\))?',
    re.DOTALL
)


def normalize_latex_spaces(latex: str) -> str:
    """
    标准化 LaTeX 公式中的空格。

    将各种空格变体统一为标准格式：
    - \frac { → \frac{
    - } { → }{
    - d x → dx, d  x → dx
    - \partial  x → \partial x (多个空格→单个空格)
    - \left( → \left(, \right) → \right)
    """
    result = latex
    # 移除 \frac 后的多余空格
    result = re.sub(r'\\frac\s*\{', r'\\frac{', result)
    # 移除相邻花括号间的多余空格
    result = re.sub(r'\}\s*\{', r'}{', result)
    # 移除 d 和变量间的空格（分母）
    result = re.sub(r'd\s+([a-zA-Z])', r'd\1', result)
    # 规范化 \partial 后的空格为单个空格
    result = re.sub(r'\\partial\s+', r'\\partial ', result)
    # 规范化 \left( 和 \right) 周围的空格
    result = re.sub(r'\\left\s*\(', r'\\left(', result)
    result = re.sub(r'\\right\s*\)', r'\\right)', result)
    return result


def extract_order(s: Optional[str]) -> Union[int, str]:
    """Extract derivative order from superscript string."""
    if s is None or s == '':
        return 1
    s = s.strip('{}')
    try:
        return int(s)
    except ValueError:
        # Return the letter as-is for symbolic orders like 'n'
        return s


def parse_ordinary_derivative(match: re.Match) -> Tuple[Union[int, str], str, str, Optional[str]]:
    """
    Parse ordinary derivative match.
    Returns: (order, variable, func_name, func_args)

    正则分组:
    - group(1): numerator order (d^order)
    - group(2): variable (dx → x)
    - group(3): denominator order (dx^2 → 2)
    - group(4): function name (f, y, etc.)
    - group(5): function arguments in (x) format
    - group(6): function arguments in {\left(x \right)} format
    """
    num_order = extract_order(match.group(1))
    var = match.group(2)
    den_order_str = match.group(3)
    func = match.group(4)
    # Try group(5) first (standard (x) args), then group(6) ({\left(x \right)} args)
    args = match.group(5) if match.group(5) else match.group(6)
    if args:
        args = args.strip()  # 清理参数中的首尾空格

    order = num_order if match.group(1) is not None else 1
    return order, var, func, args


def parse_partial_derivative(match: re.Match) -> Tuple[int, List[str], str, Optional[str]]:
    """
    Parse partial derivative match.
    Returns: (order, variables, func_name, func_args)
    """
    num_order = extract_order(match.group(1))
    var1 = match.group(2)
    var1_order = extract_order(match.group(3))
    var2 = match.group(4)
    var2_order = extract_order(match.group(5))
    func = match.group(6)
    args = match.group(7)

    variables = []
    if var1:
        variables.extend([var1] * var1_order)
    if var2:
        variables.extend([var2] * var2_order)

    # If numerator specifies total order, use it; otherwise infer from denominator
    if match.group(1) is not None:
        total_order = num_order
    else:
        total_order = len(variables)

    # Validate consistency
    if total_order != len(variables) and match.group(1) is not None and variables:
        warnings.warn(
            f"Partial derivative order mismatch: ∂^{total_order} / "
            f"∂{''.join(variables)}. Using actual variables.",
            UserWarning
        )

    return total_order, variables, func, args


def parse_partial_derivative_multi(match: re.Match) -> Tuple[int, List[str], str, Optional[str]]:
    """
    Parse partial derivative with multiple variables in denominator.
    e.g. \frac{\partial^2}{\partial x \partial y}f(x,y)
    Returns: (order, variables, func_name, func_args)
    """
    num_order = extract_order(match.group(1))
    denom = match.group(2)
    func = match.group(3)
    args = match.group(4)

    # Extract variables from denominator
    var_pattern = re.compile(r'\\partial\s+([a-zA-Z]+)(?:\^(\d+|\{[^}]+\}))?')
    variables = []
    for vm in var_pattern.finditer(denom):
        var = vm.group(1)
        v_order = extract_order(vm.group(2))
        variables.extend([var] * v_order)

    # Use numerator order if specified, otherwise infer from denominator
    total_order = num_order if match.group(1) is not None else len(variables)

    return total_order, variables, func, args


# ──────────────────────────────────────────────────────────
# Transform Functions
# ──────────────────────────────────────────────────────────

def to_lagrange(order: int, func: str, args: Optional[str], is_partial: bool = False,
                variables: Optional[List[str]] = None) -> str:
    """
    Convert to Lagrange notation.

    Ordinary: f', f'', f''', f^{(n)}
    Partial:  f_x, f_{xx}, f_{xy}
    """
    arg_str = f"({args})" if args else ""

    if is_partial:
        if not variables:
            return f"{func}{arg_str}"
        # Build subscript
        sub = ''.join(variables)
        if len(variables) > 1:
            return f"{func}_{{{sub}}}{arg_str}"
        return f"{func}_{sub}{arg_str}"
    else:
        # Ordinary derivative
        # Handle both integer and symbolic orders
        if order == 1 or order == '1':
            return f"{func}'{arg_str}"
        elif order == 2 or order == '2':
            return f"{func}''{arg_str}"
        elif order == 3 or order == '3':
            return f"{func}'''{arg_str}"
        else:
            # For symbolic orders like 'n', or higher integers
            return f"{func}^{{({order})}}{arg_str}"


def to_newton(order: int, func: str, args: Optional[str]) -> str:
    """
    Convert to Newton notation (dot notation).
    Conventionally used only for time derivatives.

    1st: \dot{y}
    2nd: \ddot{y}
    3rd+: \overset{(n)}{\dot{y}} (extended notation)
    """
    arg_str = f"({args})" if args else ""

    if order == 1:
        return f"\\dot{{{func}}}{arg_str}"
    elif order == 2:
        return f"\\ddot{{{func}}}{arg_str}"
    else:
        warnings.warn(
            f"Newton dot notation for order {order} is non-standard. "
            f"Consider using Leibniz \\frac{{d^{order}}}{{dt^{order}}}{func} "
            f"or Lagrange {func}^{{({order})}} notation instead.",
            UserWarning
        )
        return f"\\overset{{({order})}}{{\\dot{{{func}}}}}{arg_str}"


def simplify_dependencies(latex: str) -> str:
    """
    简化因变量表达式，省略自变量。

    将 f(x), f'(x), f''(x), f^{(n)}(x), y^{\frac{3}{2}}(x), \dot{y}(x), \ddot{y}(x) 等简化为 f, f', f'', f^{(n)}, y^{\frac{3}{2}}, \dot{y}, \ddot{y}
    同时处理 \left( \right) 和 {\left( \right)} 格式（保留 \left...\right）

    Args:
        latex: 输入 LaTeX 字符串

    Returns:
        简化后的 LaTeX 字符串
    """
    result = latex

    # 循环处理函数依赖，直到不再变化
    changed = True
    while changed:
        old = result

        # 步骤 1：先处理 {\left( ... \right)} 中的函数简化（保留 \left...\right）
        # 匹配 y^{\frac{3}{2}}{(x)} 或 y'{(x)} 格式（大括号内套括号）
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]'{0,3})\s*\{\s*\(\s*[^)]*?\s*\)\s*\}", r'\1', result)
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]\^{(?:[^}]|\{[^}]*\})*})\s*\{\s*\(\s*[^)]*?\s*\)\s*\}", r'\1', result)
        # 匹配 \dot{y}{(x)} 或 \ddot{y}{(x)} 格式
        result = re.sub(r"(?<!\\)(\\(?:dot|ddot|overset)\{[^\}]*\})\s*\{\s*\(\s*[^)]*?\s*\)\s*\}", r'\1', result)
        # 匹配 y{\left(x \right)} 格式（简化 y 的自变量）
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]'{0,3})\s*\{\s*\\left\s*\(\s*[^)]*?\s*\\right\s*\)\s*\}", r'\1', result)
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]\^{(?:[^}]|\{[^}]*\})*})\s*\{\s*\\left\s*\(\s*[^)]*?\s*\\right\s*\)\s*\}", r'\1', result)
        # 匹配 \dot{y}{\left(x \right)} 格式
        result = re.sub(r"(?<!\\)(\\(?:dot|ddot|overset)\{[^\}]*\})\s*\{\s*\\left\s*\(\s*[^)]*?\s*\\right\s*\)\s*\}", r'\1', result)

        # 步骤 2：处理 \left( ... \right) 中的函数简化（保留 \left...\right）
        # 匹配 \left(y'(x)\right) 格式，简化 y'(x) 为 y'
        # 使用 (?<!\\) 确保前面不是反斜杠，但 \left 后面是 (，所以不会匹配 t
        result = re.sub(r"\\left\s*\(\s*(?<!\\)([a-zA-Z]'{0,3})\s*\(\s*[^)]*?\s*\)\s*\\right\s*\)", r'\\left(\1\\right)', result)
        result = re.sub(r"\\left\s*\(\s*(?<!\\)([a-zA-Z]\^{(?:[^}]|\{[^}]*\})*})\s*\(\s*[^)]*?\s*\)\s*\\right\s*\)", r'\\left(\1\\right)', result)
        # 匹配 \left(\dot{y}(x)\right) 格式
        result = re.sub(r"\\left\s*\(\s*(?<!\\)(\\(?:dot|ddot|overset)\{[^\}]*\})\s*\(\s*[^)]*?\s*\)\s*\\right\s*\)", r'\\left(\1\\right)', result)

        # 步骤 3：处理标准 ( ... ) 格式的函数
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]'{0,3})\s*\(\s*[^)]*?\s*\)", r'\1', result)
        result = re.sub(r"(?<![a-zA-Z\\)])([a-zA-Z]\^{(?:[^}]|\{[^}]*\})*})\s*\(\s*[^)]*?\s*\)", r'\1', result)
        # 匹配 \dot{y}(x) 格式
        result = re.sub(r"(?<!\\)(\\(?:dot|ddot|overset)\{[^\}]*\})\s*\(\s*[^)]*?\s*\)", r'\1', result)

        changed = (result != old)

    return result


def _extract_derivative_order(expr: str) -> Optional[int]:
    """
    从导数表达式中提取阶数。

    Args:
        expr: 导数表达式，如 f, f', f'', \dot{y}, \ddot{y} 等

    Returns:
        导数阶数，如果无法识别则返回 None
    """
    expr = expr.strip()

    # 0 阶：普通函数 f, y
    if re.match(r"^[a-zA-Z]$", expr):
        return 0

    # Lagrange: f', f'', f'''
    if re.match(r"^[a-zA-Z]'$", expr):
        return 1
    if re.match(r"^[a-zA-Z]''$", expr):
        return 2
    if re.match(r"^[a-zA-Z]'''$", expr):
        return 3

    # Newton: \dot{...} (1 阶), \ddot{...} (2 阶)
    if re.match(r"^\\dot\{", expr):
        return 1
    if re.match(r"^\\ddot\{", expr):
        return 2

    # \overset{(n)}{\dot{...}} (n 阶)
    overset_match = re.match(r"^\\overset\{([^}]+)\}\{\\dot\{[^\}]*\}\}", expr)
    if overset_match:
        order_str = overset_match.group(1)
        try:
            return int(order_str)
        except ValueError:
            return None  # 符号阶数

    return None


def remove_power_parens(latex: str, max_order: int = 2) -> str:
    """
    去除 Lagrange 或 Newton 符号幂次项的多余括号。

    将 (y')^n 变为 y'^n，(\dot{y})^n 变为 \dot{y}^n，(y)^n 变为 y^n。
    只处理指定阶数范围内的导数（默认 2 阶及以下，包括 0 阶）。

    Args:
        latex: 输入 LaTeX 字符串
        max_order: 最大处理阶数（默认 2）。只处理此阶数及以下的导数符号。

    Returns:
        处理后的 LaTeX 字符串
    """
    result = latex

    # 步骤 1：处理 \left(...\right)^{n} 格式
    # 匹配 \left(f'\right)^{n}, \left(\dot{y}\right)^{n}, \left(y\right)^{n} 等
    def replace_left_right(match):
        inner = match.group(1)
        power_braced = match.group(2)  # 大括号内的指数
        power_plain = match.group(3)   # 无大括号的指数
        # 检查导数阶数
        order = _extract_derivative_order(inner)
        if order is not None and order <= max_order:
            # 如果原指数有大括号，保留；否则不加
            if power_braced:  # 有大括号
                return f"{inner}^{{{power_braced}}}"
            elif power_plain:  # 无大括号
                return f"{inner}^{power_plain}"
        return match.group(0)

    # 匹配 \left(...\right)^{n} 或 \left(...\right)^n
    result = re.sub(
        r"\\left\s*\(\s*([a-zA-Z]'{0,3}|\\dot\{[^\}]*\}|\\ddot\{[^\}]*\}|[a-zA-Z])\s*\\right\s*\)\s*\^\s*(?:\{([^}]+)\}|(\d+|[a-zA-Z]+))",
        replace_left_right,
        result,
        flags=re.DOTALL
    )

    # 步骤 2：处理标准 (...)^{n} 格式
    def replace_parens(match):
        inner = match.group(1)
        power_braced = match.group(2)  # 大括号内的指数
        power_plain = match.group(3)   # 无大括号的指数
        # 检查导数阶数
        order = _extract_derivative_order(inner)
        if order is not None and order <= max_order:
            if power_braced:  # 有大括号
                return f"{inner}^{{{power_braced}}}"
            elif power_plain:  # 无大括号
                return f"{inner}^{power_plain}"
        return match.group(0)

    # 匹配 (...)^{n} 或 (...)^n
    result = re.sub(
        r"\(\s*([a-zA-Z]'{0,3}|\\dot\{[^\}]*\}|\\ddot\{[^\}]*\}|[a-zA-Z])\s*\)\s*\^\s*(?:\{([^}]+)\}|(\d+|[a-zA-Z]+))",
        replace_parens,
        result,
        flags=re.DOTALL
    )

    return result


def transform_leibniz(latex: str, target: str = 'lagrange',
                       expected_var: Optional[str] = None) -> str:
    """
    Transform Leibniz derivatives in a LaTeX string to target notation.

    Args:
        latex: Input LaTeX string
        target: 'lagrange' or 'newton'
        expected_var: Expected independent variable (for validation)

    Returns:
        Transformed LaTeX string
    """
    # 标准化 LaTeX 公式中的空格
    result = normalize_latex_spaces(latex)

    # Collect all replacements to apply from right to left
    replacements = []

    # Collect partial derivatives (multi-variable pattern)
    for match in PARTIAL_MULTI_RE.finditer(result):
        order, variables, func, args = parse_partial_derivative_multi(match)

        if target == 'newton':
            partial_vars = ' '.join('\\partial ' + v for v in variables)
            warnings.warn(
                "Partial derivative " + partial_vars + " " + func +
                " cannot be converted to Newton notation. Keeping original.",
                UserWarning
            )
            continue

        replacement = to_lagrange(order, func, args, is_partial=True, variables=variables)
        replacements.append((match.start(), match.end(), replacement))

    # Collect partial derivatives (simple pattern)
    for match in PARTIAL_RE.finditer(result):
        order, variables, func, args = parse_partial_derivative(match)

        if target == 'newton':
            partial_vars = ' '.join('\\partial ' + v for v in variables)
            warnings.warn(
                "Partial derivative " + partial_vars + " " + func +
                " cannot be converted to Newton notation. Keeping original.",
                UserWarning
            )
            continue

        replacement = to_lagrange(order, func, args, is_partial=True, variables=variables)
        replacements.append((match.start(), match.end(), replacement))

    # Collect ordinary derivatives
    for match in ORDINARY_RE.finditer(result):
        order, var, func, args = parse_ordinary_derivative(match)

        if expected_var and var != expected_var:
            warnings.warn(
                f"Variable mismatch: expected '{expected_var}', found '{var}'. "
                f"Proceeding with conversion.",
                UserWarning
            )

        if target == 'lagrange':
            replacement = to_lagrange(order, func, args)
        else:  # newton
            replacement = to_newton(order, func, args)

        replacements.append((match.start(), match.end(), replacement))

    # Apply replacements from right to left to avoid position shifts
    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, replacement in replacements:
        result = result[:start] + replacement + result[end:]

    return result


def transform_and_simplify(latex: str, target: str = 'lagrange',
                           expected_var: Optional[str] = None,
                           simplify: bool = True,
                           remove_power_parens_flag: bool = False) -> str:
    """
    转换导数记号并简化因变量表达式。

    Args:
        latex: 输入 LaTeX 字符串
        target: 'lagrange' 或 'newton'
        expected_var: 用于验证的自变量
        simplify: 是否简化因变量（默认 True）
        remove_power_parens_flag: 是否去除幂次项的多余括号（默认 False）

    Returns:
        转换并简化后的 LaTeX 字符串
    """
    # 先转换导数记号
    result = transform_leibniz(latex, target=target, expected_var=expected_var)

    # 如果启用简化，简化因变量表达式
    if simplify:
        # 使用默认简化规则（简化所有函数的自变量）
        result = simplify_dependencies(result)

    # 如果启用去除幂次括号
    if remove_power_parens_flag:
        result = remove_power_parens(result, max_order=2)

    return result


# ──────────────────────────────────────────────────────────
# CLI Interface
# ──────────────────────────────────────────────────────────

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Convert Leibniz derivative notation in LaTeX to Lagrange or Newton notation.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -t lagrange "\\frac{d}{dx}f(x)"
  %(prog)s -t newton "\\frac{d^2}{dt^2}y(t)"
  %(prog)s -t lagrange -s "\\frac{d}{dx}f(x)"   # 简化函数依赖
  echo "\\frac{d}{dx}f(x)" | %(prog)s -t lagrange -s
  %(prog)s -t lagrange -o output.tex input.tex
  %(prog)s -t newton -s -r "\\frac{d^2}{dt^2}y(t)"  # 简化 + 去除幂次括号
  %(prog)s -t lagrange -s -r "\\frac{d^3}{dx^3}f(x)"  # 3 阶导数保留括号
        """
    )
    parser.add_argument(
        '-t', '--target',
        choices=['lagrange', 'newton'],
        default='lagrange',
        help='Target notation format (default: lagrange)'
    )
    parser.add_argument(
        '-v', '--var',
        default=None,
        help='Expected independent variable for validation'
    )
    parser.add_argument(
        '-s', '--simplify',
        action='store_true',
        help='Simplify function dependencies: f(x) -> f, f\'(x) -> f\', etc.'
    )
    parser.add_argument(
        '-r', '--remove-power-parens',
        action='store_true',
        help='Remove redundant parentheses in power terms: (y\')^2 -> y\'^2, (\\dot{y})^2 -> \\dot{y}^2, (y)^2 -> y^2 (0-2 order only)'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output file path (default: stdout)'
    )
    parser.add_argument(
        '--no-warnings',
        action='store_true',
        help='Suppress warning messages'
    )
    parser.add_argument(
        'input',
        nargs='?',
        help='Input LaTeX string or file path. If omitted, reads from stdin.'
    )
    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    # Suppress warnings if requested
    if args.no_warnings:
        warnings.filterwarnings('ignore')

    # Determine input source
    if args.input is None:
        # Read from stdin
        try:
            latex_input = sys.stdin.read()
        except KeyboardInterrupt:
            return 0
    elif args.input.endswith('.tex') or args.input.endswith('.txt'):
        # Read from file
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                latex_input = f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            return 1
        except IOError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return 1
    else:
        # Treat as literal LaTeX string
        latex_input = args.input

    # Transform and optionally simplify
    result = transform_and_simplify(
        latex_input,
        target=args.target,
        expected_var=args.var,
        simplify=args.simplify,
        remove_power_parens_flag=args.remove_power_parens
    )

    # Output
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(result)
        except IOError as e:
            print(f"Error writing file: {e}", file=sys.stderr)
            return 1
    else:
        print(result, end='')

    return 0


if __name__ == '__main__':
    sys.exit(main())
