# =============================================================================
# PROGNOZOWANIE: Imigracja i emigracja w UE 2025-2029
# Modele: ARIMA/Holt (szeregi czasowe, wybór per seria) i Random Forest (ML)
# Wynik: zapis prognoz do tabeli Fact_PrognozaMigracji w SQL Server
#
# Wymagania - zainstaluj przed uruchomieniem:
#   pip install pandas numpy statsmodels scikit-learn sqlalchemy pyodbc
# =============================================================================

import gzip
import io
import warnings
import pandas as pd
import numpy as np
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sqlalchemy import create_engine, text

warnings.filterwarnings('ignore')

# =============================================================================
# KONFIGURACJA
# =============================================================================

FOLDER = r'C:\Users\Roksa\Desktop\praza_inzDANE'
SERWER = 'localhost'
BAZA   = 'HurtowniaMigracje'

PLIKI = {
    'imigracja':  fr'{FOLDER}\migr_imm1ctz_tabular.tsv.gz',
    'emigracja':  fr'{FOLDER}\migr_emi1ctz_tabular.tsv.gz',
    'pkb':        fr'{FOLDER}\nama_10_pc_tabular.tsv.gz',
    'bezrobocie': fr'{FOLDER}\lfsa_urgan_tabular.tsv.gz',
}

EU27 = {
    'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR',
    'DE','EL','HU','IE','IT','LV','LT','LU','MT','NL',
    'PL','PT','RO','SK','SI','ES','SE'
}
LATA_HISTORYCZNE = [str(r) for r in range(2008, 2025)]   # 2008-2024
LATA_PROGNOZY    = list(range(2025, 2030))                # 2025-2029, 5 lat

KRAJ_ID = {k: i + 1 for i, k in enumerate(sorted(EU27))}
# ID czasu dla lat historycznych: 2008->1, ..., 2024->17
# ID czasu dla lat prognozy: 2025->18, ..., 2029->22 (kontynuacja Dim_Czas)
CZAS_ID = {2008 + i: i + 1 for i in range(17)}
CZAS_ID.update({2025 + i: 18 + i for i in range(5)})


# =============================================================================
# EXTRACT + TRANSFORM (te same funkcje co w ETL danych historycznych)
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
    kolumny_lat = [c for c in df.columns if c in LATA_HISTORYCZNE]
    wiersze = []
    for _, rzad in df.iterrows():
        for rok in kolumny_lat:
            surowa = str(rzad[rok]).strip()
            if surowa == ':' or surowa == '':
                wartosc = None
            else:
                wartosc = pd.to_numeric(surowa.split()[0], errors='coerce')
            wiersze.append({'geo': rzad['geo'], 'rok': int(rok), 'wartosc': wartosc})
    return pd.DataFrame(wiersze).sort_values(['geo', 'rok']).reset_index(drop=True)


def interpoluj_braki(df):
    wynik = df.copy()
    wynik['wartosc_uzup'] = wynik['wartosc']
    for kraj in df['geo'].unique():
        maska = wynik['geo'] == kraj
        seria = wynik.loc[maska, 'wartosc'].copy()
        if seria.isna().any():
            wynik.loc[maska, 'wartosc_uzup'] = seria.interpolate(
                method='linear', limit_direction='both').values
    return wynik


# =============================================================================
# MODELE PROGNOSTYCZNE
# =============================================================================

def prognoza_arima(seria_historyczna, n_lat=5):
    """
    Prognoza ARIMA(1,1,1) na n_lat lat w przód.
    """
    model = ARIMA(seria_historyczna, order=(1, 1, 1))
    fit = model.fit()
    prognoza = fit.forecast(steps=n_lat)
    return np.maximum(prognoza, 0)


def prognoza_holt(seria_historyczna, n_lat=5):
    """
    Prognoza metodą Holta (wygładzanie wykładnicze z trendem liniowym).
    W odróżnieniu od ARIMA(1,1,1), która szybko spłaszcza prognozę do
    wartości stałej, metoda Holta ekstrapoluje trend wzrostowy/spadkowy
    na cały horyzont prognozy - lepiej radzi sobie z seriami o wyraźnym,
    konsekwentnym trendzie (typowe dla migracji w wielu krajach UE).
    """
    model = ExponentialSmoothing(seria_historyczna, trend='add', damped_trend=False)
    fit = model.fit()
    prognoza = fit.forecast(n_lat)
    return np.maximum(prognoza, 0)


def wybierz_najlepszy_model(seria_historyczna, n_test=3):
    """
    Porównuje ARIMA(1,1,1) i metodę Holta na ostatnich n_test latach
    metodą walidacji hold-out (model trenowany bez tych lat, a następnie
    sprawdzany na nich - nie jest to walidacja krzyżowa k-fold, tylko
    jeden podział "przeszłość -> przyszłość", odpowiedni dla szeregów
    czasowych gdzie kolejność obserwacji ma znaczenie).
    Zwraca nazwę metody z niższym błędem (RMSE) dla danej serii.

    To podejście (model selection per szereg) jest lepsze niż sztywne
    przypisanie jednej metody do wszystkich krajów, bo różne kraje mają
    różny charakter trendu migracyjnego.
    """
    if len(seria_historyczna) <= n_test + 3:
        return 'ARIMA', None  # za mało danych do walidacji - użyj domyślnej

    train = seria_historyczna[:-n_test]
    test = seria_historyczna[-n_test:]

    rmse_arima = np.inf
    try:
        fit = ARIMA(train, order=(1, 1, 1)).fit()
        pred = fit.forecast(steps=n_test)
        rmse_arima = np.sqrt(mean_squared_error(test, pred))
    except Exception:
        pass

    rmse_holt = np.inf
    try:
        fit = ExponentialSmoothing(train, trend='add', damped_trend=False).fit()
        pred = fit.forecast(n_test)
        rmse_holt = np.sqrt(mean_squared_error(test, pred))
    except Exception:
        pass

    if rmse_holt < rmse_arima:
        return 'Holt', rmse_holt
    return 'ARIMA', rmse_arima


def prognoza_random_forest(lata_hist, wartosci_hist, pkb_hist, bezrobocie_hist,
                            lata_prog, pkb_prog, bezrobocie_prog):
    """
    Prognoza Random Forest z wykorzystaniem PKB per capita i stopy bezrobocia
    jako zmiennych objaśniających (oprócz samego roku).
    """
    X_train = np.column_stack([lata_hist, pkb_hist, bezrobocie_hist])
    rf = RandomForestRegressor(n_estimators=200, max_depth=4, random_state=42)
    rf.fit(X_train, wartosci_hist)

    X_pred = np.column_stack([lata_prog, pkb_prog, bezrobocie_prog])
    prognoza = rf.predict(X_pred)
    return np.maximum(prognoza, 0)





# =============================================================================
# GŁÓWNY PIPELINE
# =============================================================================

print("=" * 70)
print("PROGNOZOWANIE: Imigracja i emigracja w UE 2025-2029")
print("=" * 70)

print("\n[1/4] Wczytywanie danych historycznych...")
imm = interpoluj_braki(wczytaj_eurostat(PLIKI['imigracja'],
    {'freq':'A','unit':'NR','sex':'T','age':'TOTAL','agedef':'COMPLET','citizen':'TOTAL'}))
emi = interpoluj_braki(wczytaj_eurostat(PLIKI['emigracja'],
    {'freq':'A','unit':'NR','sex':'T','age':'TOTAL','agedef':'COMPLET','citizen':'TOTAL'}))
gdp = interpoluj_braki(wczytaj_eurostat(PLIKI['pkb'],
    {'freq':'A','unit':'CLV10_EUR_HAB','na_item':'B1GQ'}))
une = interpoluj_braki(wczytaj_eurostat(PLIKI['bezrobocie'],
    {'freq':'A','unit':'PC','sex':'T','age':'Y15-74','citizen':'TOTAL'}))

print("[2/4] Budowanie prognoz dla każdego kraju...")

wiersze_prognoz = []
id_prognozy = 1
raport_jakosci = []

for kod_kraju in sorted(EU27):
    id_kraju = KRAJ_ID[kod_kraju]

    for nazwa_typu, df_src, id_typu in [('imigracja', imm, 1), ('emigracja', emi, 2)]:

        seria = df_src[df_src['geo'] == kod_kraju].sort_values('rok')
        if len(seria) < 5:
            continue  # za mało danych dla tego kraju

        wartosci_hist = seria['wartosc_uzup'].values
        lata_hist = seria['rok'].values

        # --- Wybór najlepszej metody szeregu czasowego (ARIMA vs Holt) ---
        metoda_wybrana, rmse_walidacji = wybierz_najlepszy_model(wartosci_hist, n_test=3)

        try:
            if metoda_wybrana == 'Holt':
                prog_szereg = prognoza_holt(wartosci_hist, n_lat=len(LATA_PROGNOZY))
                nazwa_metody_szereg = 'Holt(trend liniowy)'
            else:
                prog_szereg = prognoza_arima(wartosci_hist, n_lat=len(LATA_PROGNOZY))
                nazwa_metody_szereg = 'ARIMA(1,1,1)'
        except Exception as e:
            print(f"  [UWAGA] Model szeregowy nie zbiegł dla {kod_kraju}/{nazwa_typu}: {e}")
            prog_szereg = [None] * len(LATA_PROGNOZY)
            nazwa_metody_szereg = 'ARIMA(1,1,1)'

        # --- Random Forest (z PKB i bezrobociem) ---
        pkb_seria = gdp[gdp['geo'] == kod_kraju].sort_values('rok')
        une_seria = une[une['geo'] == kod_kraju].sort_values('rok')

        if len(pkb_seria) == len(seria) and len(une_seria) == len(seria):
            # Naiwna ekstrapolacja PKB/bezrobocia na lata prognozy (do regresji RF)
            pkb_trend = np.polyfit(lata_hist, pkb_seria['wartosc_uzup'].values, 1)
            une_trend = np.polyfit(lata_hist, une_seria['wartosc_uzup'].values, 1)
            pkb_prog = np.polyval(pkb_trend, LATA_PROGNOZY)
            une_prog = np.maximum(np.polyval(une_trend, LATA_PROGNOZY), 0)

            try:
                prog_rf = prognoza_random_forest(
                    lata_hist, wartosci_hist,
                    pkb_seria['wartosc_uzup'].values, une_seria['wartosc_uzup'].values,
                    LATA_PROGNOZY, pkb_prog, une_prog
                )
            except Exception as e:
                prog_rf = [None] * len(LATA_PROGNOZY)
        else:
            prog_rf = [None] * len(LATA_PROGNOZY)

        # --- Ocena jakości modelu (RMSE walidacyjne na 3 ostatnich latach historii) ---
        raport_jakosci.append({'kraj': kod_kraju, 'typ': nazwa_typu,
                               'metoda_wybrana': metoda_wybrana, 'rmse': rmse_walidacji})

        # --- Zapis wierszy prognozy (jeden wiersz per metoda per rok) ---
        for i, rok in enumerate(LATA_PROGNOZY):
            if rok not in CZAS_ID:
                continue
            if prog_szereg[i] is not None:
                wiersze_prognoz.append({
                    'ID_prognozy': id_prognozy,
                    'ID_kraju': id_kraju,
                    'ID_czasu': CZAS_ID[rok],
                    'ID_typu_migracji': id_typu,
                    'Prognozowana_wartosc': round(float(prog_szereg[i]), 2),
                    'Metoda_prognozowania': nazwa_metody_szereg
                })
                id_prognozy += 1
            if prog_rf[i] is not None:
                wiersze_prognoz.append({
                    'ID_prognozy': id_prognozy,
                    'ID_kraju': id_kraju,
                    'ID_czasu': CZAS_ID[rok],
                    'ID_typu_migracji': id_typu,
                    'Prognozowana_wartosc': round(float(prog_rf[i]), 2),
                    'Metoda_prognozowania': 'RandomForest(PKB+bezrobocie)'
                })
                id_prognozy += 1

fact_prognoza = pd.DataFrame(wiersze_prognoz)
print(f"  Wygenerowano {len(fact_prognoza)} wierszy prognozy "
      f"({len(EU27)} krajów x 2 typy x 5 lat x 2 metody = {27*2*5*2})")

# --- Raport jakości modeli (RMSE) ---
df_raport = pd.DataFrame(raport_jakosci).dropna(subset=['rmse'])
print(f"\n[3/4] Raport jakości modeli (walidacja hold-out na 3 ostatnich latach):")
print(f"  Średnie RMSE (po wyborze najlepszej metody): {df_raport['rmse'].mean():,.0f}")
print(f"  Mediana RMSE: {df_raport['rmse'].median():,.0f}")
print(f"\n  Rozkład wybranej metody (ARIMA vs Holt):")
print(df_raport['metoda_wybrana'].value_counts().to_string())
print(f"\n  5 krajów z najlepszym dopasowaniem:")
print(df_raport.nsmallest(5, 'rmse').to_string(index=False))

# =============================================================================
# LOAD - zapis do SQL Server
# =============================================================================

print(f"\n[4/4] Łączenie z SQL Server ({SERWER})...")

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
    print(f"\n[BŁĄD] Nie można połączyć się z SQL Server: {e}")
    raise

# Czyszczenie starych prognoz przed zapisem nowych - skrypt można uruchamiać
# wielokrotnie bez ręcznego DELETE w SSMS. Bez tego kroku ponowne uruchomienie
# zduplikowałoby wiersze i poleciałby konflikt na ID_prognozy (zaczyna od 1).
print("  Czyszczenie starych prognoz z Fact_PrognozaMigracji...")
with engine.connect() as conn:
    conn.execute(text("DELETE FROM Fact_PrognozaMigracji"))
    conn.commit()

# Najpierw trzeba zapewnić, że Dim_Czas ma wiersze dla lat 2025-2029
print("  Dodawanie lat 2025-2029 do Dim_Czas (jeśli jeszcze nie istnieją)...")
with engine.connect() as conn:
    for rok in LATA_PROGNOZY:
        id_czasu = CZAS_ID[rok]
        istnieje = conn.execute(
            text("SELECT COUNT(*) FROM Dim_Czas WHERE ID_czasu = :id"),
            {"id": id_czasu}
        ).scalar()
        if istnieje == 0:
            conn.execute(
                text("INSERT INTO Dim_Czas (ID_czasu, Rok, Kwartal, Miesiac) "
                     "VALUES (:id, :rok, NULL, NULL)"),
                {"id": id_czasu, "rok": rok}
            )
    conn.commit()

print(f"  Ładowanie Fact_PrognozaMigracji ({len(fact_prognoza)} wierszy)...", end=' ')
fact_prognoza.to_sql('Fact_PrognozaMigracji', engine, if_exists='append',
                      index=False, chunksize=500)
print("OK")

print("\n[OK] Prognozowanie zakończone! Wyniki są w SQL Server.")
print("     Sprawdź w SSMS:")
print("     SELECT * FROM Fact_PrognozaMigracji ORDER BY ID_kraju, ID_czasu;")
