# -*- coding: utf-8 -*-
# =============================================================================
# ANALIZA TRENDÓW MIGRACYJNYCH W UE - eksploracja danych
# Temat: Analiza trendów migracyjnych w Unii Europejskiej
#        z wykorzystaniem metod eksploracji danych
#
# Zakres analizy:
#   1. Trendy czasowe - jak zmieniała się migracja w UE w latach 2008-2024
#   2. Korelacje - związek między PKB/bezrobociem a saldem migracji (na 1000 mieszkańców)
#   3. Klastrowanie - grupowanie krajów UE wg podobnych wzorców migracyjnych
#      (na podstawie wskaźników per capita, nie wartości bezwzględnych)
#
# Wymagania - zainstaluj przed uruchomieniem:
#   pip install pandas numpy scikit-learn scipy matplotlib seaborn sqlalchemy pyodbc
# =============================================================================

import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import pearsonr
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine

warnings.filterwarnings('ignore')

# =============================================================================
# KONFIGURACJA
# =============================================================================

SERWER = 'localhost'
BAZA   = 'HurtowniaMigracje'
FOLDER_WYKRESY = r'C:\Users\Roksa\Desktop\praza_inzDANE\wykresy'

import os
os.makedirs(FOLDER_WYKRESY, exist_ok=True)

sns.set_style('whitegrid')
plt.rcParams['figure.figsize'] = (10, 6)

# =============================================================================
# EXTRACT - wczytanie danych z hurtowni SQL Server
# =============================================================================

print("=" * 70)
print("ANALIZA TRENDÓW MIGRACYJNYCH W UE 2008-2024")
print("=" * 70)

print("\n[1/5] Łączenie z hurtownią danych (SQL Server)...")

connection_string = (
    f"mssql+pyodbc://@{SERWER}/{BAZA}"
    f"?driver=ODBC+Driver+17+for+SQL+Server"
    f"&trusted_connection=yes"
    f"&TrustServerCertificate=yes"
)
engine = create_engine(connection_string)
print(f"  Połączono z bazą: {BAZA}")

# Dane migracji (imigracja/emigracja) połączone z wymiarami
zapytanie_migracja = """
SELECT
    dk.Kod_kraju,
    dk.Nazwa_kraju,
    dk.Region,
    dc.Rok,
    tm.Nazwa_typu_migracji,
    fm.Liczba_migrantow
FROM Fact_Migracja fm
JOIN Dim_Kraj dk ON fm.ID_kraju = dk.ID_kraju
JOIN Dim_Czas dc ON fm.ID_czasu = dc.ID_czasu
JOIN Dim_TypMigracji tm ON fm.ID_typu_migracji = tm.ID_typu_migracji
"""

# Dane wskaźników kraju (PKB, bezrobocie, ludność)
zapytanie_wskazniki = """
SELECT
    dk.Kod_kraju,
    dc.Rok,
    dw.Nazwa_wskaznika,
    fw.Wartosc
FROM Fact_WskaznikKraju fw
JOIN Dim_Kraj dk ON fw.ID_kraju = dk.ID_kraju
JOIN Dim_Czas dc ON fw.ID_czasu = dc.ID_czasu
JOIN Dim_WskaznikKraju dw ON fw.ID_wskaznika_kraju = dw.ID_wskaznika_kraju
"""

print("[2/5] Wczytywanie danych migracji i wskaźników kraju...")
df_migracja = pd.read_sql(zapytanie_migracja, engine)
df_wskazniki = pd.read_sql(zapytanie_wskazniki, engine)

print(f"  Wczytano {len(df_migracja)} wierszy migracji, {len(df_wskazniki)} wierszy wskaźników")

# Przekształcenie do formatu szerokiego (łatwiejszy do analizy)
imigracja = df_migracja[df_migracja['Nazwa_typu_migracji'] == 'imigracja'][
    ['Kod_kraju', 'Rok', 'Liczba_migrantow']].rename(columns={'Liczba_migrantow': 'Imigracja'})
emigracja = df_migracja[df_migracja['Nazwa_typu_migracji'] == 'emigracja'][
    ['Kod_kraju', 'Rok', 'Liczba_migrantow']].rename(columns={'Liczba_migrantow': 'Emigracja'})

dane = imigracja.merge(emigracja, on=['Kod_kraju', 'Rok'])
dane['Saldo'] = dane['Imigracja'] - dane['Emigracja']

pkb = df_wskazniki[df_wskazniki['Nazwa_wskaznika'] == 'PKB per capita'][
    ['Kod_kraju', 'Rok', 'Wartosc']].rename(columns={'Wartosc': 'PKB'})
bezrobocie = df_wskazniki[df_wskazniki['Nazwa_wskaznika'] == 'Stopa bezrobocia'][
    ['Kod_kraju', 'Rok', 'Wartosc']].rename(columns={'Wartosc': 'Bezrobocie'})
ludnosc = df_wskazniki[df_wskazniki['Nazwa_wskaznika'] == 'Liczba ludnosci'][
    ['Kod_kraju', 'Rok', 'Wartosc']].rename(columns={'Wartosc': 'Ludnosc'})

dane = dane.merge(pkb, on=['Kod_kraju', 'Rok']).merge(bezrobocie, on=['Kod_kraju', 'Rok'])
dane = dane.merge(ludnosc, on=['Kod_kraju', 'Rok'])

# Wskaźniki na 1000 mieszkańców - niezbędne do porównań między krajami.
# Bez tego Niemcy/Francja/Hiszpania zawsze "wygrywałyby" w korelacjach
# i klastrowaniu tylko dlatego, że mają dużą populację, a nie dlatego,
# że migracja jest tam proporcjonalnie wyższa.
dane['Imigracja_na_1000'] = 1000 * dane['Imigracja'] / dane['Ludnosc']
dane['Emigracja_na_1000'] = 1000 * dane['Emigracja'] / dane['Ludnosc']
dane['Saldo_na_1000'] = 1000 * dane['Saldo'] / dane['Ludnosc']

print(f"  Połączono w jedną tabelę analityczną: {len(dane)} wierszy, kolumny: {list(dane.columns)}")


# =============================================================================
# 1. ANALIZA TRENDÓW CZASOWYCH
# =============================================================================

print("\n" + "=" * 70)
print("[3/5] ANALIZA TRENDÓW CZASOWYCH")
print("=" * 70)

trend_ue = dane.groupby('Rok')[['Imigracja', 'Emigracja', 'Saldo']].sum()

zmiana_imm = 100 * (trend_ue.loc[2024, 'Imigracja'] / trend_ue.loc[2008, 'Imigracja'] - 1)
zmiana_emi = 100 * (trend_ue.loc[2024, 'Emigracja'] / trend_ue.loc[2008, 'Emigracja'] - 1)

print(f"\nImigracja UE-27 ogółem:")
print(f"  2008: {trend_ue.loc[2008, 'Imigracja']:,.0f}")
print(f"  2024: {trend_ue.loc[2024, 'Imigracja']:,.0f}")
print(f"  Zmiana 2008->2024: {zmiana_imm:+.1f}%")

print(f"\nEmigracja UE-27 ogółem:")
print(f"  2008: {trend_ue.loc[2008, 'Emigracja']:,.0f}")
print(f"  2024: {trend_ue.loc[2024, 'Emigracja']:,.0f}")
print(f"  Zmiana 2008->2024: {zmiana_emi:+.1f}%")

# Wykres 1: trend imigracji/emigracji/salda UE ogółem
fig, ax = plt.subplots(figsize=(11, 6))
ax.plot(trend_ue.index, trend_ue['Imigracja'], marker='o', label='Imigracja', linewidth=2)
ax.plot(trend_ue.index, trend_ue['Emigracja'], marker='s', label='Emigracja', linewidth=2)
ax.plot(trend_ue.index, trend_ue['Saldo'], marker='^', label='Saldo migracji',
        linewidth=2, linestyle='--', color='green')
ax.set_xlabel('Rok')
ax.set_ylabel('Liczba osób')
ax.set_title('Trendy migracyjne w UE-27, 2008-2024')
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\01_trend_UE_ogolem.png', dpi=150)
plt.close()
print(f"\n  Zapisano wykres: 01_trend_UE_ogolem.png")

# Wykres 2: top 5 krajów z najwyższym saldem migracji (ostatnie 3 lata)
saldo_recent = dane[dane['Rok'].between(2022, 2024)].groupby('Kod_kraju')['Saldo'].mean()
top5 = saldo_recent.nlargest(5).index.tolist()

fig, ax = plt.subplots(figsize=(11, 6))
for kraj in top5:
    dane_kraj = dane[dane['Kod_kraju'] == kraj].sort_values('Rok')
    ax.plot(dane_kraj['Rok'], dane_kraj['Saldo'], marker='o', label=kraj, linewidth=2)
ax.set_xlabel('Rok')
ax.set_ylabel('Saldo migracji')
ax.set_title('Saldo migracji - 5 krajów UE z największym napływem netto (2022-2024)')
ax.legend()
ax.grid(True, alpha=0.3)
ax.axhline(y=0, color='gray', linestyle=':', linewidth=1)
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\02_top5_saldo.png', dpi=150)
plt.close()
print(f"  Zapisano wykres: 02_top5_saldo.png")
print(f"  Top 5 krajów wg salda migracji (2022-2024): {top5}")


# =============================================================================
# 2. ANALIZA KORELACJI
# =============================================================================

print("\n" + "=" * 70)
print("[4/5] ANALIZA KORELACJI")
print("=" * 70)

# Średnie wartości per kraj za cały okres - jednostka analizy to KRAJ, nie kraj-rok.
# Korelacje liczone na wskaźniku Saldo_na_1000 (nie wartości bezwzględnej Saldo),
# żeby uniknąć dominacji dużych krajów (DE, FR, ES) tylko z powodu ich populacji.
dane_per_kraj = dane.groupby('Kod_kraju').agg({
    'Imigracja': 'mean', 'Emigracja': 'mean', 'Saldo': 'mean',
    'Imigracja_na_1000': 'mean', 'Emigracja_na_1000': 'mean', 'Saldo_na_1000': 'mean',
    'PKB': 'mean', 'Bezrobocie': 'mean'
})

r_pkb, p_pkb = pearsonr(dane_per_kraj['Saldo_na_1000'], dane_per_kraj['PKB'])
r_une, p_une = pearsonr(dane_per_kraj['Saldo_na_1000'], dane_per_kraj['Bezrobocie'])

print(f"\nKorelacja Pearsona (n={len(dane_per_kraj)} krajów, średnie 2008-2024):")
print(f"  Saldo migracji/1000 mieszkańców vs PKB per capita:    r = {r_pkb:+.3f}  (p = {p_pkb:.4f})")
print(f"  Saldo migracji/1000 mieszkańców vs stopa bezrobocia:  r = {r_une:+.3f}  (p = {p_une:.4f})")

istotnosc_pkb = "statystycznie istotna" if p_pkb < 0.05 else "statystycznie nieistotna"
istotnosc_une = "statystycznie istotna" if p_une < 0.05 else "statystycznie nieistotna"
print(f"\n  Korelacja z PKB jest {istotnosc_pkb} (próg p<0.05)")
print(f"  Korelacja z bezrobociem jest {istotnosc_une} (próg p<0.05)")

# Wykres 3: macierz korelacji (heatmapa) - na wskaźnikach per 1000 mieszkańców
macierz_korelacji = dane_per_kraj[
    ['Imigracja_na_1000', 'Emigracja_na_1000', 'Saldo_na_1000', 'PKB', 'Bezrobocie']].corr()

fig, ax = plt.subplots(figsize=(8, 6))
sns.heatmap(macierz_korelacji, annot=True, fmt='.2f', cmap='coolwarm', center=0,
            square=True, linewidths=0.5, ax=ax)
ax.set_title('Macierz korelacji - migracja (na 1000 mieszkańców)\ni wskaźniki gospodarcze, średnie 2008-2024')
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\03_macierz_korelacji.png', dpi=150)
plt.close()
print(f"\n  Zapisano wykres: 03_macierz_korelacji.png")

# Wykres 4: scatter plot saldo (na 1000 mieszkańców) vs PKB z linią trendu
fig, ax = plt.subplots(figsize=(9, 6))
sns.regplot(data=dane_per_kraj, x='PKB', y='Saldo_na_1000', ax=ax,
            scatter_kws={'alpha': 0.6, 's': 80}, line_kws={'color': 'red'})
for kraj in dane_per_kraj.index:
    ax.annotate(kraj, (dane_per_kraj.loc[kraj, 'PKB'], dane_per_kraj.loc[kraj, 'Saldo_na_1000']),
                fontsize=8, alpha=0.7, xytext=(3, 3), textcoords='offset points')
ax.set_xlabel('PKB per capita (EUR, ceny stałe 2010)')
ax.set_ylabel('Średnie saldo migracji na 1000 mieszkańców (2008-2024)')
ax.set_title(f'Saldo migracji (na 1000 mieszkańców) a PKB per capita (r={r_pkb:.3f})')
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\04_saldo_vs_pkb.png', dpi=150)
plt.close()
print(f"  Zapisano wykres: 04_saldo_vs_pkb.png")


# =============================================================================
# 3. KLASTROWANIE KRAJÓW (KMeans)
# =============================================================================

print("\n" + "=" * 70)
print("[5/5] KLASTROWANIE KRAJÓW WG WZORCÓW MIGRACYJNYCH")
print("=" * 70)

# Klastrowanie na wskaźnikach per 1000 mieszkańców (nie wartościach bezwzględnych) -
# inaczej kraje o dużej populacji (DE, FR, ES) zawsze trafiałyby do odrębnego
# klastra tylko z powodu skali, a nie odmiennego charakteru migracji.
cechy = dane_per_kraj[['Imigracja_na_1000', 'Emigracja_na_1000', 'PKB', 'Bezrobocie']].dropna()

# Standaryzacja - niezbędna przy KMeans, bo cechy mają bardzo różne skale
# (PKB w tysiącach euro, imigracja w setkach tysięcy osób)
scaler = StandardScaler()
X = scaler.fit_transform(cechy)

# Metoda "elbow" - sprawdzenie kilku wartości k
print("\nMetoda 'elbow' (suma kwadratów odległości wewnątrz klastrów):")
inercje = []
for k in range(2, 7):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km.fit(X)
    inercje.append(km.inertia_)
    print(f"  k={k}: inertia={km.inertia_:.1f}")

# k=3 jako kompromis interpretowalności i jakości podziału
K_WYBRANE = 3
km_final = KMeans(n_clusters=K_WYBRANE, random_state=42, n_init=10)
cechy['Klaster'] = km_final.fit_predict(X)

print(f"\nWybrano k={K_WYBRANE} (interpretowalny podział, widoczny 'łokieć' na wykresie elbow)")
print(f"\nPrzypisanie krajów do klastrów:")
for klaster in sorted(cechy['Klaster'].unique()):
    kraje_w_klastrze = cechy[cechy['Klaster'] == klaster].index.tolist()
    print(f"  Klaster {klaster}: {kraje_w_klastrze}")

print(f"\nŚrednie wartości cech per klaster:")
print(cechy.groupby('Klaster')[['Imigracja_na_1000', 'Emigracja_na_1000', 'PKB', 'Bezrobocie']].mean().to_string())

# Wykres 5: elbow plot
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(range(2, 7), inercje, marker='o', linewidth=2)
ax.set_xlabel('Liczba klastrów (k)')
ax.set_ylabel('Inertia (suma kwadratów odległości)')
ax.set_title('Metoda elbow - wybór optymalnej liczby klastrów')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\05_elbow_plot.png', dpi=150)
plt.close()
print(f"\n  Zapisano wykres: 05_elbow_plot.png")

# Wykres 6: scatter plot klastrów (imigracja na 1000 mieszkańców vs PKB)
fig, ax = plt.subplots(figsize=(10, 7))
kolory = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12']
for klaster in sorted(cechy['Klaster'].unique()):
    subset = cechy[cechy['Klaster'] == klaster]
    ax.scatter(subset['PKB'], subset['Imigracja_na_1000'], s=120,
               color=kolory[klaster], label=f'Klaster {klaster}', alpha=0.8, edgecolors='black')
    for kraj in subset.index:
        ax.annotate(kraj, (subset.loc[kraj, 'PKB'], subset.loc[kraj, 'Imigracja_na_1000']),
                    fontsize=9, xytext=(5, 5), textcoords='offset points')
ax.set_xlabel('PKB per capita (EUR)')
ax.set_ylabel('Średnia imigracja roczna na 1000 mieszkańców')
ax.set_title(f'Klastrowanie krajów UE wg wzorców migracyjnych (k={K_WYBRANE})')
ax.legend()
plt.tight_layout()
plt.savefig(f'{FOLDER_WYKRESY}\\06_klastry_kraje.png', dpi=150)
plt.close()
print(f"  Zapisano wykres: 06_klastry_kraje.png")

# =============================================================================
# PODSUMOWANIE
# =============================================================================

print("\n" + "=" * 70)
print("[OK] ANALIZA ZAKOŃCZONA")
print("=" * 70)
print(f"\nWykresy zapisane w: {FOLDER_WYKRESY}")
print("  01_trend_UE_ogolem.png       - trend imigracji/emigracji/salda 2008-2024")
print("  02_top5_saldo.png            - top 5 krajów wg salda migracji")
print("  03_macierz_korelacji.png     - korelacje migracja vs PKB/bezrobocie")
print("  04_saldo_vs_pkb.png          - wykres rozrzutu saldo vs PKB")
print("  05_elbow_plot.png            - wybór liczby klastrów")
print("  06_klastry_kraje.png         - wizualizacja klastrów krajów")
