import os

from data_processing.data_access.data_access_local import DataAccessLocal
from antivirus_transform import AntivirusTransform 


# create parameters
input_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "test-data", "input"))
output_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))
local_conf = {
    "input_folder": input_folder,
    "output_folder": output_folder,
}
antivirus_params = {
    "antivirus_input_column": "contents",
    "antivirus_output_column": "virus_detection",
    "antivirus_clamd_socket": "../.tmp/clamd.ctl",
}
if __name__ == "__main__":
    # Here we show how to run outside of ray
    # Create and configure the transform.
    transform = AntivirusTransform(antivirus_params)
    # Use the local data access to read a parquet table.
    data_access = DataAccessLocal(local_conf)
    table = data_access.get_table(os.path.join(input_folder, "sample.parquet"))
    print(f"input table: {table}")
    # Transform the table
    table_list, metadata = transform.transform(table)
    print(f"\noutput table: {table_list}")
    print(f"output metadata : {metadata}")