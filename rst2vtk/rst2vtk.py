from ansys.mapdl import reader as pymapdl_reader
result = pymapdl_reader.read_binary('file.rst')
result.save_as_vtk(
     "file.vtu",
     rsets=None,
     result_types=['ENS', 'EEL'],
     progress_bar=True
)