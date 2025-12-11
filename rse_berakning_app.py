import streamlit as st
import pandas as pd
import datetime
from io import BytesIO

# Hjälpfunktion: parsa tal med svenska tusentalsavgränsare och komma
def parse_swe_number(text):
    # Robust parser som hanterar tusentalsavgränsare, decimaler och suffix (k/miljoner)
    if isinstance(text, (int, float)):
        return float(text)
    if text is None:
        return 0.0
    s = str(text).lower()
    # ersätt icke-brytande mellanslag och trim
    s = s.replace("\u00a0", " ").strip()

    multiplier = 1.0
    # Hantera vanliga svenska storleks-suffix
    if any(term in s for term in ["miljon", "miljoner", "m"]):
        multiplier = 1_000_000.0
        # ta bort ord/suffix
        s = s.replace("miljoner", "").replace("miljon", "").replace("m", "")
    elif any(term in s for term in ["tusen", "k"]):
        multiplier = 1_000.0
        s = s.replace("tusen", "").replace("k", "")

    # Ta bort alla bokstäver och andra tecken utom siffror, punkt, komma och minus
    allowed = set("0123456789.,-")
    s = "".join(ch for ch in s if ch in allowed)

    # Om både punkt och komma förekommer, anta att komma är decimal och punkt tusen
    if "," in s and "." in s:
        s = s.replace(".", "")  # ta bort tusen-punkter
    # Ta bort mellanslag (om kvar) som tusentalsavgränsare
    s = s.replace(" ", "")
    # Ersätt komma med punkt för decimal
    s = s.replace(",", ".")

    # Om det finns flera punkter, behåll endast den sista som decimalpunkt
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]).replace(".", "") + "." + parts[-1]

    try:
        return float(s) * multiplier
    except Exception:
        return 0.0

# Callback för att formatera skuld-fältet live
def format_skuld_input():
    raw = st.session_state.get("skuld_start", "")
    parsed = parse_swe_number(raw)
    # Formatera med tusentalsavgränsare, utan decimaler
    formatted = f"{parsed:,.0f}".replace(",", " ") if parsed else ""
    st.session_state["skuld_start"] = formatted

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
    senaste_ffd = st.date_input("Senaste ffd (styr upplupen ränta och framtida betaldagar)", datetime.date(losendag.year, losendag.month, 1))
    slutbetdag = st.date_input("Slutbetdag (förfallodag)", senaste_ffd + datetime.timedelta(days=730))
    # Textfält med tusentalsavgränsare (mellanslag) för skuld
    skuld_start = st.text_input(
        "Låneskuld vid lösendag",
        value=f"{1_000_000:,.0f}".replace(",", " "),
        key="skuld_start",
        placeholder="Exempel: 1 000 000 eller 1,5 miljoner"
    )
    amortering = st.number_input("Amortering per period", min_value=0.0, value=0.0, step=1000.0)
    kundranta = st.number_input("Kundränta (%)", min_value=0.0, value=4.0, step=0.1) / 100
    egen_startranta = st.number_input("Egen startränta (effektivränta, %)", min_value=0.0, value=3.0, step=0.1) / 100
    egen_jamforranta = st.number_input("Egen jämförränta (effektivränta, %)", min_value=0.0, value=2.0, step=0.1) / 100
    frekvens = st.selectbox("Betalningsfrekvens", ["Månad", "Kvartal", "År"])
    submit = st.form_submit_button("Beräkna RSE")

if submit:
    # Parsea och validera skuld från textfältet
    skuld_start = parse_swe_number(skuld_start)
    if skuld_start < 0:
        skuld_start = 0.0

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
    
    # Beräkna första förfallodagen baserat på senaste_ffd
    if senaste_ffd.month + steg > 12:
        ny_manad = (senaste_ffd.month + steg) % 12
        ny_ar = senaste_ffd.year + (senaste_ffd.month + steg - 1) // 12
    else:
        ny_manad = senaste_ffd.month + steg
        ny_ar = senaste_ffd.year
    forsta_ffd = datetime.date(ny_ar, ny_manad, senaste_ffd.day)
    
    # Använd första_ffd som bas för att beräkna alla förfallodagar
    ffd_referens = senaste_ffd

    while datum < slutbetdag and skuld > 0:
        # Beräkna nästa förfallodag baserat på senaste_ffd och periodsteg
        if ffd_referens.month + steg > 12:
            ny_manad = (ffd_referens.month + steg) % 12
            ny_ar = ffd_referens.year + (ffd_referens.month + steg - 1) // 12
        else:
            ny_manad = ffd_referens.month + steg
            ny_ar = ffd_referens.year
        datum_nasta = datetime.date(ny_ar, ny_manad, ffd_referens.day)

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
        ffd_referens = datum_nasta

    df = pd.DataFrame(betalningsplan)
    total_rse = max(0,df["Nuvärde"].sum())
    
    # Beräkna upplupen ränta från senaste ffd till lösendag
    dagar_upplupen = days_30_360_european(senaste_ffd, losendag)
    upplupen_ranta = kundranta * skuld_start * (dagar_upplupen / 360)
    
    totalt_att_betala = total_rse + upplupen_ranta
       
    st.success(f"Ränteskillnadsersättning: {round(total_rse):,} kr".replace(",", " "))
    st.info(f"Upplupen Kundränta för perioden {senaste_ffd.strftime('%Y-%m-%d')} - {losendag.strftime('%Y-%m-%d')}: {round(upplupen_ranta):,} kr".replace(",", " "))
    st.success(f"**Totalt att betala: {round(totalt_att_betala):,} kr**".replace(",", " "))

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
