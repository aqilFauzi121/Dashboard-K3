# sheet_io.py
import pandas as pd
from config import SHEET_ID, SHEET_NAME

def read_sheet_values(_gc):
    try:
        sh = _gc.open_by_key(SHEET_ID)
    except Exception as e:
        raise RuntimeError(f"Gagal membuka spreadsheet dengan ID {SHEET_ID}: {e}")

    try:
        ws = sh.worksheet(SHEET_NAME)
    except Exception as e:
        raise RuntimeError(f"Gagal membuka worksheet '{SHEET_NAME}': {e}")

    records = ws.get_all_records()
    if records:
        df = pd.DataFrame(records)
    else:
        headers = ws.row_values(1)
        df = pd.DataFrame(columns=headers)
    return df

def append_row(gc, row_values):
    """
    Menambahkan satu baris ke worksheet.
    """
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(SHEET_NAME)
    ws.append_row(row_values, value_input_option="USER_ENTERED")