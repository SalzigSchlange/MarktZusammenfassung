import os
import smtplib
import sqlite3
from datetime import date
from email.message import EmailMessage

# Market Libraries
from edgar import set_identity, get_filings
import OpenDartReader
import requests
from google import genai  # Updated import for 2026 SDK

# 1. INITIALIZATION
set_identity(os.getenv('EMAIL_USER'))
# New Client initialization for google-genai
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

# 2. THE SUMMARIZER
def get_summary(text, market):
    prompt = f"""
    Summary of {market} financial report. 
    One paragraph in English. Focus on Revenue, Net Income, and Outlook.
    If you spot anything unusual, mention it.
    TEXT: {text[:30000]}
    """
    try:
        # Updated syntax for google-genai SDK
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
        return "Summary failed."

# 3. THE DISCOVERY
def main():
    init_db()
    # Hardcoded to Friday for this test as requested
    today = "2026-05-08"
    digest = []
    print(f"Starting sweep for {today}...")

    # US Sweep (EDGAR)
    try:
        us_filings = get_filings(filing_date=today, form=["10-K", "10-Q"])
        for f in us_filings:
            if is_new(f.accession_no):
                print(f"Processing US: {f.company}")
                summary = get_summary(f.markdown(), "US")
                digest.append(f"US: {f.company} ({f.ticker})\n{summary}")
                mark_done(f.accession_no)
    except Exception as e:
        print(f"EDGAR Error: {e}")

    # Japan Sweep (EDINET)
    try:
        jp_url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date={today}&type=2"
        jp_res = requests.get(jp_url).json()
        for doc in jp_res.get('results', []):
            if doc.get('docTypeCode') in ['120', '140'] and is_new(doc['docID']):
                digest.append(f"JP: {doc['filerName']}\n{doc['docDescription']}")
                mark_done(doc['docID'])
    except Exception as e:
        print(f"EDINET Error: {e}")

    # Korea Sweep (DART)
    try:
        kr_date = today.replace("-", "")
        kr_filings = dart.list(start=kr_date, end=kr_date, pblntf_detail_ty='a001')
        if kr_filings is not None:
            for _, row in kr_filings.iterrows():
                if is_new(row['rcept_no']):
                    digest.append(f"KR: {row['corp_name']}\nAnnual Report Filed.")
                    mark_done(row['rcept_no'])
    except Exception as e:
        print(f"DART Error: {e}")

    # 4. THE EMAIL
    if digest:
        print(f"Found {len(digest)} items. Sending email...")
        msg = EmailMessage()
        msg.set_content("\n\n---\n\n".join(digest))
        msg['Subject'] = f"Daily Financial Digest - {today}"
        msg['From'] = os.getenv('EMAIL_USER')
        msg['To'] = os.getenv('EMAIL_USER')

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASSWORD'))
            smtp.send_message(msg)
        print("Email sent successfully.")
    else:
        print("No new filings to report today.")

if __name__ == "__main__":
    main()