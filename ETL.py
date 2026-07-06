# =============================================================================
# ETL: Hurtownia danych - Migracje UE 2008-2024
# Wersja z bezpośrednim załadowaniem do SQL Server
#
# Wymagania - zainstaluj przed uruchomieniem:
#   pip install pandas sqlalchemy pyodbc
#
# Uruchomienie:
#   python etl_migracje_UE_sqlserver.py
# =============================================================================

import gzip
import io
import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

# =============================================================================
# KONFIGURACJA - zmień tylko te wartości jeśli coś się różni
# =============================================================================

FOLDER = r'C:\Users\Roksa\Desktop\praza_inzDANE'   # folder z plikami .tsv.gz
SERWER = 'localhost'                                 # nazwa serwera z SSMS
BAZA   = 'HurtowniaMigracje'                        # nazwa bazy danych

PLIKI = {
    'imigracja':  fr'{FOLDER}\migr_imm1ctz_tabular_tsv.gz',
    'emigracja':  fr'{FOLDER}\migr_emi1ctz_tabular_tsv.gz',
    'ludnosc':    fr'{FOLDER}\demo_gind_tabular_tsv.gz',
    'pkb':        fr'{FOLDER}\nama_10_pc_tabular_tsv.gz',
    'bezrobocie': fr'{FOLDER}\lfsa_urgan_tabular_tsv.gz',
}

EU27 = {
    'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR',
    'DE','EL','HU','IE','IT','LV','LT','LU','MT','NL',
    'PL','PT','RO','SK','SI','ES','SE'
}
LATA = [str(r) for r in range(2008, 2025)]

# =============================================================================
# FUNKCJE ETL
# =============================================================================

def wczytaj_eurostat(sciezka, filtry):
    with gzip.open(sciezka, 'rt', encoding='utf-8') as f:
        raw = f.read()
    nazwy_wymiarow = raw.split('\n')[0].split('\t')[0].split(',')
    nazwy_wymiarow[-1] = nazwy_wymiarow[-1].split('\\')[0]
    df = pd.read_csv(io.StringIO(raw), sep='\t', dtype=str)
    wymiary = df[df.columns[0]].str.split(',', expand=True)
    wymiary.columns = nazwy_wymiarow
    df = pd.concat([wymiary, df.iloc[:, 1:]], axis=1)
    df.columns = [c.strip() for c in df.columns]
    for k, v in filtry.items():
        if k in df.columns:
            df = df[df[k] == v]
    df = df[df['geo'].isin(EU27)]
    kolumny_lat = [c for c in df.columns if c in LATA]
    wiersze = []
    for _, rzad in df.iterrows():
        for rok in kolumny_lat:
            surowa = str(rzad[rok]).strip()
            if surowa == ':' or surowa == '':
                wartosc, flaga = None, ':'
            else:
                czesci = surowa.split()
                wartosc = pd.to_numeric(czesci[0], errors='coerce')
                flaga = czesci[1] if len(czesci) > 1 else ''
            wiersze.append({'geo': rzad['geo'], 'rok': int(rok),
                            'wartosc': wartosc, 'flaga': flaga})
    return pd.DataFrame(wiersze).sort_values(['geo','rok']).reset_index(drop=True)


def interpoluj_braki(df):
    wynik = df.copy()
    wynik['wartosc_uzup'] = wynik['wartosc']
    wynik['flaga_etl'] = ''
    for kraj in df['geo'].unique():
        maska = wynik['geo'] == kraj
        seria = wynik.loc[maska, 'wartosc'].copy()
        braki = seria.isna()
        if braki.any():
            wynik.loc[maska, 'wartosc_uzup'] = seria.interpolate(
                method='linear', limit_direction='both').values
            wynik.loc[maska & braki, 'flaga_etl'] = 'i'
    return wynik


# =============================================================================
# EXTRACT + TRANSFORM
# =============================================================================

print("=" * 60)
print("ETL: Migracje UE 2008-2024 → SQL Server")
print("=" * 60)

print("\n[Extract] Wczytywanie plików Eurostatu...")
imm = wczytaj_eurostat(PLIKI['imigracja'], {'freq':'A','unit':'NR','sex':'T','age':'TOTAL','agedef':'COMPLET','citizen':'TOTAL'})
emi = wczytaj_eurostat(PLIKI['emigracja'], {'freq':'A','unit':'NR','sex':'T','age':'TOTAL','agedef':'COMPLET','citizen':'TOTAL'})
pop = wczytaj_eurostat(PLIKI['ludnosc'],   {'freq':'A','indic_de':'AVG'})
gdp = wczytaj_eurostat(PLIKI['pkb'],       {'freq':'A','unit':'CLV10_EUR_HAB','na_item':'B1GQ'})
une = wczytaj_eurostat(PLIKI['bezrobocie'],{'freq':'A','unit':'PC','sex':'T','age':'Y15-74','citizen':'TOTAL'})

print("[Transform] Interpolacja braków...")
imm = interpoluj_braki(imm)
emi = interpoluj_braki(emi)
pop = interpoluj_braki(pop)
gdp = interpoluj_braki(gdp)
une = interpoluj_braki(une)

# =============================================================================
# BUDOWANIE TABEL
# =============================================================================

KRAJE_NAZWY = {
    'AT':'Austria','BE':'Belgia','BG':'Bulgaria','HR':'Chorwacja','CY':'Cypr',
    'CZ':'Czechy','DK':'Dania','EE':'Estonia','FI':'Finlandia','FR':'Francja',
    'DE':'Niemcy','EL':'Grecja','HU':'Wegry','IE':'Irlandia','IT':'Wlochy',
    'LV':'Lotwa','LT':'Litwa','LU':'Luksemburg','MT':'Malta','NL':'Holandia',
    'PL':'Polska','PT':'Portugalia','RO':'Rumunia','SK':'Slowacja',
    'SI':'Slowenia','ES':'Hiszpania','SE':'Szwecja'
}
DATY_UE = {
    'AT':'1995-01-01','BE':'1958-01-01','BG':'2007-01-01','HR':'2013-07-01',
    'CY':'2004-05-01','CZ':'2004-05-01','DK':'1973-01-01','EE':'2004-05-01',
    'FI':'1995-01-01','FR':'1958-01-01','DE':'1958-01-01','EL':'1981-01-01',
    'HU':'2004-05-01','IE':'1973-01-01','IT':'1958-01-01','LV':'2004-05-01',
    'LT':'2004-05-01','LU':'1958-01-01','MT':'2004-05-01','NL':'1958-01-01',
    'PL':'2004-05-01','PT':'1986-01-01','RO':'2007-01-01','SK':'2004-05-01',
    'SI':'2004-05-01','ES':'1986-01-01','SE':'1995-01-01'
}
REGIONY = {
    'AT':'Europa Srodkowa','BE':'Europa Zachodnia','BG':'Europa Wschodnia',
    'HR':'Europa Poludniowa','CY':'Europa Poludniowa','CZ':'Europa Srodkowa',
    'DK':'Europa Polnocna','EE':'Europa Polnocna','FI':'Europa Polnocna',
    'FR':'Europa Zachodnia','DE':'Europa Zachodnia','EL':'Europa Poludniowa',
    'HU':'Europa Srodkowa','IE':'Europa Zachodnia','IT':'Europa Poludniowa',
    'LV':'Europa Polnocna','LT':'Europa Polnocna','LU':'Europa Zachodnia',
    'MT':'Europa Poludniowa','NL':'Europa Zachodnia','PL':'Europa Srodkowa',
    'PT':'Europa Poludniowa','RO':'Europa Wschodnia','SK':'Europa Srodkowa',
    'SI':'Europa Srodkowa','ES':'Europa Poludniowa','SE':'Europa Polnocna'
}

kody = sorted(EU27)
KRAJ_ID = {k: i+1 for i, k in enumerate(kody)}
CZAS_ID = {2008+i: i+1 for i in range(17)}

dim_kraj = pd.DataFrame({
    'ID_kraju': range(1,28),
    'Nazwa_kraju': [KRAJE_NAZWY[k] for k in kody],
    'Kod_kraju': kody,
    'Region': [REGIONY[k] for k in kody],
    'Data_przystapienia_UE': [DATY_UE[k] for k in kody]
})

dim_czas = pd.DataFrame({
    'ID_czasu': range(1,18),
    'Rok': range(2008,2025),
    'Kwartal': [None]*17,
    'Miesiac': [None]*17
})

dim_typ = pd.DataFrame({
    'ID_typu_migracji': [1,2],
    'Nazwa_typu_migracji': ['imigracja','emigracja'],
    'Kategoria': ['Przeplywy migracyjne','Przeplywy migracyjne']
})

dim_zrodlo = pd.DataFrame({
    'ID_zrodla': [1,2,3,4,5],
    'Nazwa_zrodla': ['Eurostat']*5,
    'Kod_tabeli': ['migr_imm1ctz','migr_emi1ctz','demo_gind','nama_10_pc','lfsa_urgan'],
    'Typ_zrodla': ['API TSV']*5,
    'Opis_filtra': [
        'freq=A, unit=NR, sex=T, age=TOTAL, agedef=COMPLET, citizen=TOTAL',
        'freq=A, unit=NR, sex=T, age=TOTAL, agedef=COMPLET, citizen=TOTAL',
        'freq=A, indic_de=AVG',
        'freq=A, unit=CLV10_EUR_HAB, na_item=B1GQ',
        'freq=A, unit=PC, sex=T, age=Y15-74, citizen=TOTAL'
    ]
})

dim_wsk = pd.DataFrame({
    'ID_wskaznika_kraju': [1,2,3],
    'Nazwa_wskaznika': ['Liczba ludnosci','PKB per capita','Stopa bezrobocia'],
    'Jednostka': ['osoby','EUR (ceny stale 2010)','%'],
    'Opis': [
        'Srednia roczna liczba ludnosci (demo_gind)',
        'PKB per capita w euro, ceny stale 2010 (nama_10_pc)',
        'Stopa bezrobocia osob 15-74, ogolem (lfsa_urgan)'
    ]
})

# Fact_Migracja
wiersze_mig = []
for df_src, id_typu, id_zrodla in [(imm,1,1),(emi,2,2)]:
    for _, r in df_src.iterrows():
        if r['geo'] not in KRAJ_ID or r['rok'] not in CZAS_ID:
            continue
        czy_interp = 1 if r['flaga_etl'] == 'i' else 0
        flaga = r['flaga'] if r['flaga'] not in [':',''] else None
        wiersze_mig.append({
            'ID_kraju': KRAJ_ID[r['geo']],
            'ID_czasu': CZAS_ID[r['rok']],
            'ID_typu_migracji': id_typu,
            'ID_zrodla': id_zrodla,
            'Liczba_migrantow': int(round(r['wartosc_uzup'])) if pd.notna(r['wartosc_uzup']) else None,
            'Czy_interpolowane': czy_interp,
            'Flaga_jakosci': flaga
        })

fact_mig = pd.DataFrame(wiersze_mig)
fact_mig.insert(0, 'ID_migracji', range(1, len(fact_mig)+1))

# Fact_WskaznikKraju
wiersze_wsk = []
for df_src, id_wsk, id_zrodla in [(pop,1,3),(gdp,2,4),(une,3,5)]:
    for _, r in df_src.iterrows():
        if r['geo'] not in KRAJ_ID or r['rok'] not in CZAS_ID:
            continue
        flaga = r['flaga'] if r['flaga'] not in [':',''] else None
        wiersze_wsk.append({
            'ID_kraju': KRAJ_ID[r['geo']],
            'ID_czasu': CZAS_ID[r['rok']],
            'ID_wskaznika_kraju': id_wsk,
            'ID_zrodla': id_zrodla,
            'Wartosc': round(float(r['wartosc_uzup']),2) if pd.notna(r['wartosc_uzup']) else None,
            'Czy_interpolowane': 1 if r['flaga_etl']=='i' else 0,
            'Flaga_jakosci': flaga
        })

fact_wsk = pd.DataFrame(wiersze_wsk)
fact_wsk.insert(0, 'ID_faktu_wskaznika', range(1, len(fact_wsk)+1))

# =============================================================================
# LOAD - połączenie z SQL Server i zapis
# =============================================================================

print(f"\n[Load] Łączenie z SQL Server ({SERWER})...")

# Połączenie przez Windows Authentication (tak jak w SSMS)
connection_string = (
    f"mssql+pyodbc://@{SERWER}/{BAZA}"
    f"?driver=ODBC+Driver+17+for+SQL+Server"
    f"&trusted_connection=yes"
    f"&TrustServerCertificate=yes"
)

try:
    engine = create_engine(connection_string)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"  Połączono z bazą: {BAZA}")
except Exception as e:
    print(f"\n[BŁĄD] Nie można połączyć się z SQL Server!")
    print(f"  {e}")
    print(f"\n  Sprawdź czy:")
    print(f"  1. SQL Server jest uruchomiony")
    print(f"  2. Baza '{BAZA}' istnieje (utwórz ją w SSMS: CREATE DATABASE {BAZA})")
    print(f"  3. Masz zainstalowany sterownik ODBC 17:")
    print(f"     https://aka.ms/downloadmsodbcsql")
    raise

# Zapis w odpowiedniej kolejności (wymiary przed faktami!)
tabele = [
    (dim_kraj,   'Dim_Kraj'),
    (dim_czas,   'Dim_Czas'),
    (dim_typ,    'Dim_TypMigracji'),
    (dim_zrodlo, 'Dim_ZrodloDanych'),
    (dim_wsk,    'Dim_WskaznikKraju'),
    (fact_mig,   'Fact_Migracja'),
    (fact_wsk,   'Fact_WskaznikKraju'),
]

for df_tab, nazwa in tabele:
    print(f"  Ładowanie {nazwa} ({len(df_tab)} wierszy)...", end=' ')
    df_tab.to_sql(
        nazwa,
        engine,
        if_exists='append',   # dopisuje do istniejącej tabeli (nie nadpisuje)
        index=False,
        chunksize=500
    )
    print("OK")

print("\n[OK] ETL zakończony! Dane są w SQL Server.")
print(f"     Otwórz SSMS i sprawdź bazę: {BAZA}")