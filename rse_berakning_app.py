import streamlit as st
import pandas as pd
import datetime
from io import BytesIO

# Funktion för europeisk 30/360-dagberäkning
def days_30_360_european(start_date, end_date):
    d1 = min(start_date.day, 30)
    d2 = min(end_date.day, 30)
    return (end_date.year - start_date.year) * 360 + (end_date.month - start_date.month) * 30 + (d2 - d1)

# Streamlit-app
st.title("Beräkning av Ränteskillnadsersättning (RSE) efter lagändring 2025-07-01")

with st.form("rse_form"):
    st.subheader("Inmatning")
    losendag = st.date_input("Lösendag (start för beräkning)", datetime.date.today())
    slutbetdag = st.date_input("Slutbetdag (förfallodag)", datetime.date.today() + datetime.timedelta(days=365))
    skuld_start = st.number_input("Låneskuld vid lösendag", min_value=0.0, value=1_000_000.0, step=10000.0)
    amortering = st.number_input("Amortering per period", min_value=0.0, value=0.0, step=1000.0)
    egen_startranta = st.number_input("Egen startränta (%)", min_value=0.0, value=3.0, step=0.1) / 100
    egen_jamforranta = st.number_input("Egen jämförränta (%)", min_value=0.0, value=2.0, step=0.1) / 100
    frekvens = st.selectbox("Betalningsfrekvens", ["Månad", "Kvartal", "År"])
    submit = st.form_submit_button("Beräkna RSE")

if submit:
    # Bestäm periodsteg
    if frekvens == "Månad":
        steg = 1
    elif frekvens == "Kvartal":
        steg = 3
    else:
        steg = 12

    betalningsplan = []
    datum = losendag
    skuld = skuld_start

    while datum < slutbetdag and skuld > 0:
        # Nästa betalningsdatum
        if datum.month + steg > 12:
            ny_manad = (datum.month + steg) % 12
            ny_ar = datum.year + (datum.month + steg - 1) // 12
        else:
            ny_manad = datum.month + steg
            ny_ar = datum.year
        ny_dag = min(datum.day, 28)  # undvik problem med t.ex. 31 februari
        datum_nasta = datetime.date(ny_ar, ny_manad, ny_dag)

        if datum_nasta > slutbetdag:
            datum_nasta = slutbetdag

        dagar = days_30_360_european(datum, datum_nasta)
        periodandel = dagar / 360

        betalning = (egen_startranta - egen_jamforranta) * skuld * periodandel
        diskonteringsfaktor = 1 / ((1 + egen_jamforranta) ** (days_30_360_european(losendag, datum_nasta) / 360))
        nuvarde = betalning * diskonteringsfaktor

        betalningsplan.append({
            "Datum": datum_nasta,
            "Skuld vid start": round(skuld, 2),
            "Skillnad ränta": round(betalning, 2),
            "Disk.faktor": round(diskonteringsfaktor, 6),
            "Nuvärde": max(0,round(nuvarde, 2))
        })
        
        skuld = max(0, skuld - amortering)
        datum = datum_nasta

    df = pd.DataFrame(betalningsplan)
    total_rse = max(0,df["Nuvärde"].sum())
       
    st.success(f"Total RSE: {round(total_rse)} kr")

    # Lägg till en summeringsrad i DataFrame:n
    sum_row = {
        "Datum": "Summa",
        "Skuld vid start": "",
        "Skillnad ränta": df["Skillnad ränta"].sum(),
        "Disk.faktor": "",
        "Nuvärde": df["Nuvärde"].sum()
    }
    df = pd.concat([df, pd.DataFrame([sum_row])], ignore_index=True)
    
    # Säkerställ att alla icke-numeriska värden i numeriska kolumner är None
    for col in ["Skuld vid start", "Skillnad ränta", "Disk.faktor", "Nuvärde"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Formatera kolumner med tusentalsavgränsare och decimaler
    styler = df.style.format({
        "Skuld vid start": "{:,.2f} kr",
        "Skillnad ränta": "{:,.2f} kr",
        "Nuvärde": "{:,.2f} kr",
        "Disk.faktor": "{:.6f}"
    }, na_rep="").set_properties(**{
        "text-align": "right"
    }).set_properties(subset=["Datum"], **{
        "text-align": "left"
    })
    
    def highlight_sum_row(row):
        return ['font-weight: bold' if row["Datum"] == "Summa" else '' for _ in row]

    styler = styler.apply(highlight_sum_row, axis=1)

    if df["Nuvärde"].sum()>0:
        st.subheader("Nuvärdesberäkning RSE")
        # Rendera Styler som HTML
        html_table = styler.to_html()
        
        # Visa tabellen i Streamlit
        st.markdown(html_table, unsafe_allow_html=True)

        # Export till Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="RSE-matris")
        st.download_button("Ladda ner som Excel", data=output.getvalue(), file_name="rse_2025.xlsx")
