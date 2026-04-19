"""robot_cli_core — shared infrastructure for all robot CLIs.

Every robot CLI imports from this package. Robot-specific code only needs
to define: JointMap, MockClient, RealClient stub, and manifest.txt.
"""
__version__ = "0.1.0"
