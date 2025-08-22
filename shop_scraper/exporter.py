import os
from typing import List, Dict, Any

import pandas as pd


COLUMNS = [
    "ID",
    "Title",
    "URL",
    "Image",
    "Description",
    "Price",
    "Old price",
    "Currency",
    "custom_label_0",
]


def export_records(records: List[Dict[str, Any]], output_prefix: str) -> None:
    df = pd.DataFrame(records, columns=COLUMNS)
    os.makedirs(os.path.dirname(output_prefix) or ".", exist_ok=True)
    csv_path = f"{output_prefix}.csv"
    xlsx_path = f"{output_prefix}.xlsx"
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)