def waterfall_enrichment(df):
    """Simulates Clay-style waterfall enrichment"""
    df = df.copy()
    mask = df['Email'].isnull()
    
    # Generate fake emails for missing ones
    df.loc[mask, 'Email'] = (
        df.loc[mask, 'Name'].str.lower().str.replace(" ", ".") + 
        "@" + df.loc[mask, 'Company'].str.lower() + ".com"
    )
    return df
