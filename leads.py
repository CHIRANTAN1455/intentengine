import pandas as pd

def get_mock_leads():
    data = [
        {"Name": "Sarah Chen", "Title": "Head of Talent", "Company": "NovaFlow", 
         "Signal": "Posted about hiring struggles", "Intent Score": 92, 
         "LinkedIn Activity": "High", "Email": "sarah@novaflow.ai"},
        {"Name": "Rahul Sharma", "Title": "VP Sales", "Company": "PulseLabs", 
         "Signal": "Complained about outbound conversion", "Intent Score": 88, 
         "LinkedIn Activity": "High", "Email": None},
        {"Name": "Priya Patel", "Title": "Founder", "Company": "ScaleHire", 
         "Signal": "Recent funding + hiring", "Intent Score": 95, 
         "LinkedIn Activity": "Very High", "Email": "priya@scalehire.in"},
        {"Name": "Amit Verma", "Title": "Growth Lead", "Company": "TribeWorks", 
         "Signal": "Posted about sales team scaling", "Intent Score": 79, 
         "LinkedIn Activity": "Medium", "Email": None},
    ]
    return pd.DataFrame(data)

def filter_high_intent(df, min_score=75):
    return df[df['Intent Score'] >= min_score].copy()
