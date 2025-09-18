# auth.py
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
from config import SCOPES

@st.cache_resource
def get_gspread_client():
    try:
        # Ambil service account info dari secrets sesuai struktur Anda
        service_account_info = dict(st.secrets["service_account"])
        
        # Buat credentials dari dictionary
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        return gc
        
    except KeyError as e:
        raise FileNotFoundError(f"Service account credentials tidak ditemukan di secrets: {e}")
    except Exception as e:
        raise RuntimeError(f"Gagal membuat gspread client: {e}")