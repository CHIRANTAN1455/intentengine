import streamlit as st
from datetime import datetime

def show_metrics(df):
    col1, col2, col3 = st.columns(3)
    col1.metric("Qualified Leads", len(df))
    col2.metric("Avg Intent Score", f"{df['Intent Score'].mean():.1f}")
    col3.metric("Avg Response Potential", "High" if df['Intent Score'].mean() > 85 else "Medium")
