import os
import smtplib
import sqlite3
import time
from datetime import date
from email.message import EmailMessage

# Market Libraries
from edgar import set_identity, get_filings
import OpenDartReader
import requests
from google import genai  # Corrected 2026 SDK

# 1. INITIALIZATION
set_identity(os.getenv('EMAIL_USER'))
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
dart = OpenDartReader(os.getenv('DART_API_KEY'))

def init_db():
    conn = sqlite3.connect('processed_filings.db')
    conn.execute('CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY)')
    conn.close()

def is_new(filing_id):
    conn = sqlite3.connect('processed_filings.db')
    res = conn.execute('SELECT 1 FROM filings WHERE id=?', (filing_id,)).fetchone()
    conn.close()
    return res is None

def mark_done(filing_id):
    conn = sqlite3.connect('processed_filings.db')
    conn.execute('INSERT INTO filings VALUES (?)', (filing_id,))
    conn.commit()
    conn.close()

def get_summary(text, market):
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=f"Summarize this {market} filing in one English paragraph. Focus on Revenue, Net Income, and Outlook. If there is anything unusual also mention that: {text[:30000]}"
        )
        return response.text
    except Exception as e:
        print(f"AI Error ({market}): {e}")
        return "Summary generation failed."

def main():
    init_db()
    target_date = "2026-05-08" 
    digest = []
    # FORCE an entry so we can test the email even if the markets fail
    digest.append("SYSTEM CHECK: The agent started the sweep.")
    
    print(f"Starting Global Sweep for {target_date}...")

    # --- US (EDGAR) ---
    try:
        us_filings = get_filings(filing_date=target_date, form=["10-K", "10-Q"])
        for f in us_filings:
            if is_new(f.accession_no):
                print(f"Summarizing US: {f.company}...")
                # FIXED: Removed .ticker and used f.company
                summary = get_summary(f.markdown(), "US")
                digest.append(f"US: {f.company}\n{summary}")
                mark_done(f.accession_no)
    except Exception as e:
        print(f"EDGAR Error: {e}")

    # --- S. KOREA (DART) ---
    try:
        kr_date = target_date.replace("-", "")
        # FIXED: Corrected argument name to 'pblntf_ty'
        kr_filings = dart.list(start=kr_date, end=kr_date, pblntf_ty='A') 
        if kr_filings is not None and not kr_filings.empty:
            for _, row in kr_filings.iterrows():
                if is_new(row['rcept_no']):
                    digest.append(f"KR: {row['corp_name']}\nAnnual Report Filed.")
                    mark_done(row['rcept_no'])
    except Exception as e:
        print(f"DART Error: {e}")

    # (Keep your Japan/Email logic the same)
    # ...

    # --- MARKET 2: JAPAN (EDINET) ---
    try:
        jp_url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date={target_date}&type=2"
        jp_res = requests.get(jp_url).json()
        for doc in jp_res.get('results', []):
            if doc.get('docTypeCode') in ['120', '140'] and is_new(doc['docID']):
                print(f"Summarizing JP: {doc['filerName']}...")
                # In POC, we summarize description; full text requires type=1 download
                digest.append(f"JP: {doc['filerName']}\nForm: {doc['docDescription']}")
                mark_done(doc['docID'])
    except Exception as e:
        print(f"EDINET Error: {e}")


    # --- 4. DELIVERY ---
    if digest:
        print(f"Digest compiled ({len(digest)} items). Sending email...")
        msg = EmailMessage()
        msg.set_content("\n\n" + "="*30 + "\n\n".join(digest))
        msg['Subject'] = f"Global Financial Digest - {target_date}"
        msg['From'] = os.getenv('EMAIL_USER')
        msg['To'] = os.getenv('EMAIL_USER')

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASSWORD'))
            smtp.send_message(msg)
        print("Email sent successfully.")
    else:
        print("No new filings found across all markets.")

if __name__ == "__main__":
    main()