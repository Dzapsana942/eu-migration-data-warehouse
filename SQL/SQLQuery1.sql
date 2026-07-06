CREATE DATABASE HurtowniaMigracje;

CREATE TABLE Dim_Kraj (
    ID_kraju               INT          PRIMARY KEY,
    Nazwa_kraju            VARCHAR(100) NOT NULL,
    Kod_kraju              VARCHAR(10)  NOT NULL,
    Region                 VARCHAR(50)  NULL,
    Data_przystapienia_UE  DATE         NULL
);

CREATE TABLE Dim_Czas (
    ID_czasu  INT PRIMARY KEY,
    Rok       INT NOT NULL,
    Kwartal   INT NULL,
    Miesiac   INT NULL
);

CREATE TABLE Dim_TypMigracji (
    ID_typu_migracji     INT          PRIMARY KEY,
    Nazwa_typu_migracji  VARCHAR(100) NOT NULL,
    Kategoria            VARCHAR(50)  NULL
);

CREATE TABLE Dim_ZrodloDanych (
    ID_zrodla     INT          PRIMARY KEY,
    Nazwa_zrodla  VARCHAR(100) NOT NULL,
    Kod_tabeli    VARCHAR(50)  NOT NULL,
    Typ_zrodla    VARCHAR(50)  NULL,
    Opis_filtra   VARCHAR(255) NULL
);

CREATE TABLE Dim_WskaznikKraju (
    ID_wskaznika_kraju  INT          PRIMARY KEY,
    Nazwa_wskaznika     VARCHAR(100) NOT NULL,
    Jednostka           VARCHAR(50)  NOT NULL,
    Opis                VARCHAR(255) NULL
);

CREATE TABLE Fact_Migracja (
    ID_migracji        BIGINT       PRIMARY KEY,
    ID_kraju           INT          NOT NULL,
    ID_czasu           INT          NOT NULL,
    ID_typu_migracji   INT          NOT NULL,
    ID_zrodla          INT          NOT NULL,
    Liczba_migrantow   INT          NULL,
    Czy_interpolowane  BIT          NOT NULL DEFAULT 0,
    Flaga_jakosci      VARCHAR(20)  NULL,
    CONSTRAINT FK_Migracja_Kraj   FOREIGN KEY (ID_kraju)         REFERENCES Dim_Kraj(ID_kraju),
    CONSTRAINT FK_Migracja_Czas   FOREIGN KEY (ID_czasu)         REFERENCES Dim_Czas(ID_czasu),
    CONSTRAINT FK_Migracja_Typ    FOREIGN KEY (ID_typu_migracji) REFERENCES Dim_TypMigracji(ID_typu_migracji),
    CONSTRAINT FK_Migracja_Zrodlo FOREIGN KEY (ID_zrodla)        REFERENCES Dim_ZrodloDanych(ID_zrodla),
    CONSTRAINT UQ_Migracja_NaturalKey UNIQUE (ID_kraju, ID_czasu, ID_typu_migracji, ID_zrodla)
);

CREATE TABLE Fact_WskaznikKraju (
    ID_faktu_wskaznika  BIGINT        PRIMARY KEY,
    ID_kraju            INT           NOT NULL,
    ID_czasu            INT           NOT NULL,
    ID_wskaznika_kraju  INT           NOT NULL,
    ID_zrodla           INT           NOT NULL,
    Wartosc             DECIMAL(18,2) NOT NULL,
    Czy_interpolowane   BIT           NOT NULL DEFAULT 0,
    Flaga_jakosci       VARCHAR(20)   NULL,
    CONSTRAINT FK_Wskaznik_Kraj    FOREIGN KEY (ID_kraju)           REFERENCES Dim_Kraj(ID_kraju),
    CONSTRAINT FK_Wskaznik_Czas    FOREIGN KEY (ID_czasu)           REFERENCES Dim_Czas(ID_czasu),
    CONSTRAINT FK_Wskaznik_Typ     FOREIGN KEY (ID_wskaznika_kraju) REFERENCES Dim_WskaznikKraju(ID_wskaznika_kraju),
    CONSTRAINT FK_Wskaznik_Zrodlo  FOREIGN KEY (ID_zrodla)          REFERENCES Dim_ZrodloDanych(ID_zrodla),
    CONSTRAINT UQ_Wskaznik_NaturalKey UNIQUE (ID_kraju, ID_czasu, ID_wskaznika_kraju, ID_zrodla)
);

CREATE TABLE Fact_PrognozaMigracji (
    ID_prognozy           BIGINT        PRIMARY KEY,
    ID_kraju              INT           NOT NULL,
    ID_czasu              INT           NOT NULL,
    ID_typu_migracji      INT           NOT NULL,
    Prognozowana_wartosc  DECIMAL(18,2) NOT NULL,
    Metoda_prognozowania  VARCHAR(100)  NOT NULL,
    Data_utworzenia       DATETIME      NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT FK_Prognoza_Kraj FOREIGN KEY (ID_kraju)         REFERENCES Dim_Kraj(ID_kraju),
    CONSTRAINT FK_Prognoza_Czas FOREIGN KEY (ID_czasu)         REFERENCES Dim_Czas(ID_czasu),
    CONSTRAINT FK_Prognoza_Typ  FOREIGN KEY (ID_typu_migracji) REFERENCES Dim_TypMigracji(ID_typu_migracji)
);

CREATE INDEX IX_Fact_Migracja_Kraj_Czas ON Fact_Migracja(ID_kraju, ID_czasu);
CREATE INDEX IX_Fact_Migracja_Typ       ON Fact_Migracja(ID_typu_migracji);
CREATE INDEX IX_Fact_Migracja_Zrodlo    ON Fact_Migracja(ID_zrodla);

CREATE INDEX IX_Fact_Wskaznik_Kraj_Czas ON Fact_WskaznikKraju(ID_kraju, ID_czasu);
CREATE INDEX IX_Fact_Wskaznik_Typ       ON Fact_WskaznikKraju(ID_wskaznika_kraju);
CREATE INDEX IX_Fact_Wskaznik_Zrodlo    ON Fact_WskaznikKraju(ID_zrodla);

CREATE INDEX IX_Fact_Prognoza_Kraj_Czas ON Fact_PrognozaMigracji(ID_kraju, ID_czasu);
CREATE INDEX IX_Fact_Prognoza_Typ       ON Fact_PrognozaMigracji(ID_typu_migracji);

CREATE VIEW V_Saldo_Migracji AS
SELECT
    fm.ID_kraju,
    fm.ID_czasu,
    SUM(CASE WHEN tm.Nazwa_typu_migracji = 'imigracja' THEN fm.Liczba_migrantow ELSE 0 END) AS Imigracja,
    SUM(CASE WHEN tm.Nazwa_typu_migracji = 'emigracja' THEN fm.Liczba_migrantow ELSE 0 END) AS Emigracja,
    SUM(CASE WHEN tm.Nazwa_typu_migracji = 'imigracja' THEN fm.Liczba_migrantow ELSE 0 END)
    - SUM(CASE WHEN tm.Nazwa_typu_migracji = 'emigracja' THEN fm.Liczba_migrantow ELSE 0 END) AS Saldo
FROM Fact_Migracja fm
JOIN Dim_TypMigracji tm ON fm.ID_typu_migracji = tm.ID_typu_migracji
WHERE tm.Nazwa_typu_migracji IN ('imigracja','emigracja')
GROUP BY fm.ID_kraju, fm.ID_czasu;

SELECT name FROM sys.tables;

SELECT COUNT(*) FROM Fact_Migracja;
SELECT TOP 10 * FROM Fact_Migracja;
SELECT * FROM V_Saldo_Migracji WHERE ID_kraju = 1;


-- Pokazuje wszystkie prognozy migracji posortowane wg kraju i roku
-- (caly zbior prognoz 2025-2029, obie metody: ARIMA/Holt i RandomForest)
--ID_kraju = 1 — to Austria (w Twojej Dim_Kraj kraje s¹ ponumerowane alfabetycznie po kodzie, AT jest pierwsze)
--ID_czasu = 18 — to rok 2025 (bo lata historyczne 2008-2024 maj¹ ID 1-17, a prognoza zaczyna siê od ID 18)
--ID_typu_migracji — 1 to imigracja, 2 to emigracja

--Holt(trend liniowy) — patrzy tylko na historiê tej jednej liczby (np. ile osób emigrowa³o z Austrii ka¿dego roku 2008-2024) i kontynuuje ten sam kierunek zmian. Jeœli liczba ros³a z roku na rok, Holt zak³ada ¿e dalej bêdzie ros³a w podobnym tempie.
--RandomForest(PKB+bezrobocie) — to inne podejœcie, uczenie maszynowe. Zamiast patrzeæ tylko na sam¹ historiê migracji, bierze pod uwagê dodatkowo PKB i stopê bezrobocia danego kraju i na tej podstawie zgaduje wynik.
--Dlaczego dla tego samego roku/kraju s¹ dwie ró¿ne liczby?
--Bo to dwie niezale¿ne prognozy tej samej rzeczywistoœci — jak dwóch ró¿nych ekspertów, którzy inaczej licz¹ tê sam¹ rzecz.
--Np. wiersz 1 i 2: dla Austrii (ID_kraju=1), rok 2025 (ID_czasu=18), emigracja (typ=2):
--Holt mówi: 83 045 osób
--RandomForest mówi: 76 784 osoby
--Ró¿nica miêdzy nimi (~6 tys.) pokazuje, ¿e metody siê nie do koñca zgadzaj¹ — 
--co jest normalne i ciekawe do skomentowania w pracy: nie ma jednej "prawdziwej" prognozy, s¹ ró¿ne podejœcia z ró¿nymi za³o¿eniami.
SELECT * FROM Fact_PrognozaMigracji ORDER BY ID_kraju, ID_czasu;

--tabele
SELECT name FROM sys.tables;

-- Saldo migracji (imigracja minus emigracja) dla Austrii (ID_kraju=1)
-- wszystkie lata 2008-2024 - dane licza sie automatycznie z widoku
-- V_Saldo_Migracji, nie sa zapisane jako osobna kolumna w tabeli
SELECT * FROM V_Saldo_Migracji WHERE ID_kraju = 1;


-- Prognoza imigracji (ID_typu_migracji=1) dla Polski na lata 2025-2029,
-- pokazana obiema metodami obok siebie (ARIMA/Holt i RandomForest)
-- zeby mozna bylo porownac jak roznia sie wyniki obu modeli
SELECT dk.Kod_kraju, dc.Rok, fp.Prognozowana_wartosc, fp.Metoda_prognozowania
FROM Fact_PrognozaMigracji fp
JOIN Dim_Kraj dk ON fp.ID_kraju = dk.ID_kraju
JOIN Dim_Czas dc ON fp.ID_czasu = dc.ID_czasu
WHERE dk.Kod_kraju = 'PL' AND fp.ID_typu_migracji = 1
ORDER BY dc.Rok, fp.Metoda_prognozowania;
