# debug_sheet_access_fixed.py
# Script untuk test akses Google Sheets sesuai struktur secrets Anda
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

def test_sheet_access():
    """Test akses ke Google Sheets dan coba append data"""
    try:
        # Load credentials dari secrets sesuai struktur Anda
        service_account_info = dict(st.secrets["service_account"])
        creds = Credentials.from_service_account_info(
            service_account_info, 
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
        )
        
        # Test gspread client
        gc = gspread.authorize(creds)
        st.success("✅ Gspread client berhasil dibuat")
        
        # Test buka spreadsheet
        sheet_id = st.secrets["SHEET_ID"]
        sh = gc.open_by_key(sheet_id)
        st.success(f"✅ Spreadsheet berhasil dibuka: {sh.title}")
        
        # Test buka worksheet
        ws = sh.worksheet("Sheet1")
        st.success(f"✅ Worksheet berhasil dibuka: {ws.title}")
        
        # Test baca data
        records = ws.get_all_records()
        st.success(f"✅ Data berhasil dibaca: {len(records)} baris")
        
        # Show some data info
        if records:
            st.write("Sample data (first row):", records[0])
        
        # Test write permission dengan append test row
        if st.button("Test Append Row"):
            test_row = [
                999,  # No
                "18/09/2025",  # Tanggal Temuan
                "TEST USER",  # Penemu
                "18/09/2025",  # Tanggal Sosialisasi
                "Test Data",  # Detail Temuan
                "Dinoyo",  # Penyulang
                "Test Beban",  # Beban
                "Test Pemilik",  # Nama Pemilik/Penanggungjawab
                "Test Alamat",  # Alamat
                "-7.9999, 112.9999",  # Koordinat
                "Lower",  # Level Resiko (contoh)
                "#3d3d3d"  # Color (contoh untuk Lower)
            ]
            try:
                ws.append_row(test_row, value_input_option="USER_ENTERED")
                st.success("✅ Test append berhasil! Cek Google Sheets Anda.")
                st.balloons()
            except Exception as append_error:
                st.error(f"❌ Gagal append: {append_error}")
                st.write("Error details:", str(append_error))
                
        # Test credentials info
        with st.expander("Debug Info"):
            st.write("Service Account Email:", service_account_info.get('client_email', 'N/A'))
            st.write("Project ID:", service_account_info.get('project_id', 'N/A'))
            st.write("Sheet ID:", sheet_id)
                
    except Exception as e:
        st.error(f"❌ Error: {e}")
        st.write("Error type:", type(e).__name__)
        import traceback
        st.code(traceback.format_exc())

# Untuk menjalankan debug, buat file terpisah atau tambahkan ke app.py
if __name__ == "__main__":
    st.title("Debug Sheet Access")
    test_sheet_access()