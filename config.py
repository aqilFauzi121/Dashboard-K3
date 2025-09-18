# config.py
import streamlit as st

# Ambil dari secrets.toml sesuai struktur Anda
SHEET_ID = st.secrets["SHEET_ID"]
SHEET_NAME = "Sheet1"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]