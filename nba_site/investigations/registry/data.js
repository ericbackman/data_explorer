// ─────────────────────────────────────────────────────────────────────────────
// REGISTRY_DATA — the curated catalog of public dataset sources.
//
// This file is hand-maintained (and periodically re-verified). Each entry is a
// place where large, public, frequently-updated data actually lives — either a
// meta-registry (a catalog of many datasets) or a single high-value source.
//
// Loaded by index.html via a plain <script> tag, so the page works from file://
// with no fetch/CORS. Keep this as a single `const REGISTRY_DATA = {...}`.
//
// Field reference (per source):
//   name      display name
//   url       canonical home / data-access page
//   domain    one of the keys in DOMAINS below (drives color + grouping)
//   blurb     1–2 sentences: what it is and why people pull from it
//   scale     human-readable size/volume ("100M+ records", "petabyte-scale")
//   cadence   "live" | "daily" | "periodic" | "dump"   (drives the cadence filter)
//             live    = updates continuously / intraday
//             daily   = refreshed ~daily
//             periodic= weekly/monthly/quarterly/annual releases
//             dump    = big static/bulk snapshots you download wholesale
//   access    array of access methods: "API" | "Bulk" | "Cloud" | "Query" | "Web"
//   format    primary file/serialization formats
//   note      optional standout fact
// ─────────────────────────────────────────────────────────────────────────────

const REGISTRY_DATA = {
  updated: "2026-06-14",

  domains: {
    registry: { label: "Registries & ML",     color: "#a78bfa", blurb: "Meta-catalogs and ML-ready hubs — one entry point to thousands of datasets." },
    ocean:    { label: "Ocean & Marine",      color: "#22d3ee", blurb: "Marine biodiversity, oceanography, fisheries, reefs, and bathymetry." },
    gov:      { label: "Government & Economy", color: "#34d399", blurb: "Official statistics portals — macro, demographic, and fiscal data." },
    world:    { label: "World, Society & Climate", color: "#f59e0b", blurb: "Global indicators, news-event streams, maps, and climate records." },
    finance:  { label: "Finance & Markets",   color: "#f472b6", blurb: "Filings, prices, prediction markets, and on-chain crypto data." },
  },

  // Order within a domain ≈ how often it's the right first stop.
  sources: [
    // ── Registries & ML ─────────────────────────────────────────────────────
    {
      name: "Hugging Face Datasets", url: "https://huggingface.co/datasets", domain: "registry",
      blurb: "The default hub for ML-ready datasets — text, image, audio, and tabular — versioned with git-LFS and streamable without a full download.",
      scale: "200k+ datasets", cadence: "live", access: ["API", "Bulk", "Query"], format: "Parquet, Arrow, JSON",
      note: "`datasets` library streams shards lazily — train on TB-scale corpora without downloading them.",
    },
    {
      name: "Kaggle Datasets", url: "https://www.kaggle.com/datasets", domain: "registry",
      blurb: "The largest community dataset commons, attached to competitions and public notebooks. Great for tidy, analysis-ready CSVs.",
      scale: "400k+ datasets", cadence: "live", access: ["API", "Bulk"], format: "CSV, SQLite, Parquet",
      note: "`kaggle datasets download -d <owner>/<slug>` pulls any public set from the CLI.",
    },
    {
      name: "AWS Open Data Registry", url: "https://registry.opendata.aws/", domain: "registry",
      blurb: "Petabyte-scale datasets hosted free on S3 under AWS's sponsorship program — Common Crawl, Sentinel imagery, OBIS, genomics, and more.",
      scale: "300+ datasets, PB-scale", cadence: "live", access: ["Cloud", "Bulk"], format: "Parquet, COG, netCDF, WARC",
      note: "Co-locate compute in the same region and egress is free — the model for 'too big to download'.",
    },
    {
      name: "Google Dataset Search", url: "https://datasetsearch.research.google.com/", domain: "registry",
      blurb: "A search engine over dataset metadata (schema.org markup) across the open web — the fastest way to discover who publishes a given dataset.",
      scale: "Indexes ~45M datasets", cadence: "live", access: ["Web"], format: "—",
      note: "Discovery layer, not a host — it points you to the source.",
    },
    {
      name: "data.gov", url: "https://data.gov/", domain: "registry",
      blurb: "The US federal open-data catalog, aggregating datasets from every agency through a CKAN backend with a clean metadata API.",
      scale: "300k+ datasets", cadence: "live", access: ["API", "Bulk"], format: "CSV, JSON, GeoJSON",
    },
    {
      name: "Zenodo", url: "https://zenodo.org/", domain: "registry",
      blurb: "CERN-operated open repository that mints a DOI for any dataset — the canonical home for citable research data dumps across every field.",
      scale: "Millions of records", cadence: "live", access: ["API", "Bulk"], format: "Any (archived)",
    },
    {
      name: "OpenML", url: "https://www.openml.org/", domain: "registry",
      blurb: "ML datasets bundled with tasks, runs, and benchmark results — built for reproducible experiments, queryable straight from scikit-learn.",
      scale: "5k+ datasets, 10M+ runs", cadence: "live", access: ["API"], format: "ARFF, Parquet",
    },
    {
      name: "UCI ML Repository", url: "https://archive.ics.uci.edu/", domain: "registry",
      blurb: "The classic teaching/benchmark archive — Iris, Adult, Wine — small, clean, well-documented sets that anchor countless papers.",
      scale: "650+ datasets", cadence: "dump", access: ["Bulk", "API"], format: "CSV",
    },
    {
      name: "Common Crawl", url: "https://commoncrawl.org/", domain: "registry",
      blurb: "A free monthly snapshot of the open web — the raw material behind most large language models. Hosted on S3, queryable by URL index.",
      scale: "~2.5B pages / month, PB total", cadence: "dump", access: ["Cloud", "Bulk"], format: "WARC, WET, WAT",
      note: "Each monthly crawl is ~250 TB; the full archive spans 2008→today.",
    },
    {
      name: "Wikimedia Dumps", url: "https://dumps.wikimedia.org/", domain: "registry",
      blurb: "Complete twice-monthly dumps of Wikipedia and sister projects — full article text, revision history, and pageview logs.",
      scale: "~20 GB compressed (en)", cadence: "dump", access: ["Bulk"], format: "XML, SQL",
      note: "Hourly pageview counts are a free, real-world demand signal.",
    },
    {
      name: "Internet Archive", url: "https://archive.org/", domain: "registry",
      blurb: "Books, web captures (Wayback), audio, and software at civilization scale, with item-level APIs and bulk access.",
      scale: "100+ PB", cadence: "live", access: ["API", "Bulk"], format: "Many",
    },
    {
      name: "data.world", url: "https://data.world/", domain: "registry",
      blurb: "A collaborative data catalog with hosted SQL — useful for tidy community datasets and quick joins without local setup.",
      scale: "Hundreds of thousands of datasets", cadence: "live", access: ["API", "Query"], format: "CSV, SQL",
    },

    // ── Ocean & Marine ──────────────────────────────────────────────────────
    {
      name: "OBIS", url: "https://obis.org/", domain: "ocean",
      blurb: "The Ocean Biodiversity Information System — UNESCO/IOC's integrated record of where marine life has been observed, harvested from 5,000+ datasets.",
      scale: "100M+ records · 160k species", cadence: "live", access: ["API", "Cloud", "Bulk"], format: "Darwin Core, GeoParquet",
      note: "Full dataset mirrored as GeoParquet on AWS Open Data for large-scale analysis.",
    },
    {
      name: "GBIF", url: "https://www.gbif.org/", domain: "ocean",
      blurb: "The Global Biodiversity Information Facility — every digitized species occurrence (marine and terrestrial), with reproducible download DOIs.",
      scale: "3B+ occurrence records", cadence: "daily", access: ["API", "Bulk"], format: "Darwin Core Archive",
      note: "Each download gets a citable DOI snapshot — reproducibility built in.",
    },
    {
      name: "Argo Float Program", url: "https://argo.ucsd.edu/data/", domain: "ocean",
      blurb: "A global array of ~4,000 robotic floats profiling temperature and salinity of the upper 2,000 m — the backbone of modern ocean state estimation.",
      scale: "3M+ profiles · ~100k/yr", cadence: "live", access: ["Bulk", "Cloud"], format: "netCDF",
      note: "Data are public within hours of collection via the GDAC mirrors.",
    },
    {
      name: "NOAA NCEI", url: "https://www.ncei.noaa.gov/", domain: "ocean",
      blurb: "One of the world's largest environmental archives — ocean temperature/salinity climatologies (WOA), bathymetry, and the historical climate record.",
      scale: "40+ PB", cadence: "live", access: ["API", "Bulk", "Cloud"], format: "netCDF, CSV",
    },
    {
      name: "ERDDAP (NOAA CoastWatch)", url: "https://coastwatch.pfeg.noaa.gov/erddap/", domain: "ocean",
      blurb: "A unified data server that exposes thousands of gridded and tabular ocean datasets through one consistent, machine-friendly URL grammar.",
      scale: "Thousands of datasets", cadence: "live", access: ["API", "Query"], format: "CSV, JSON, netCDF",
      note: "Swap the file extension in the URL to change output format — built for scripts.",
    },
    {
      name: "Copernicus Marine Service", url: "https://marine.copernicus.eu/", domain: "ocean",
      blurb: "The EU's operational ocean service — global and regional reanalysis, analysis, and forecast of physics and biogeochemistry, with a no-quota toolbox.",
      scale: "Global, multi-decade", cadence: "daily", access: ["API", "Bulk"], format: "netCDF, Zarr",
      note: "`copernicusmarine` Python toolbox subsets and streams without size limits.",
    },
    {
      name: "NASA Earthdata / Ocean Color", url: "https://www.earthdata.nasa.gov/", domain: "ocean",
      blurb: "Satellite remote sensing — sea-surface temperature, chlorophyll, and ocean color from MODIS/VIIRS/PACE — plus all of NASA's Earth-observing archive.",
      scale: "Tens of PB", cadence: "daily", access: ["API", "Cloud", "Bulk"], format: "HDF, netCDF, COG",
    },
    {
      name: "Global Fishing Watch", url: "https://globalfishingwatch.org/our-apis/", domain: "ocean",
      blurb: "AIS-derived apparent fishing effort and vessel identity — maps industrial activity across the world's oceans, free for non-commercial use.",
      scale: "Global daily effort grids", cadence: "daily", access: ["API", "Bulk"], format: "CSV, GeoTIFF",
    },
    {
      name: "EMODnet", url: "https://emodnet.ec.europa.eu/", domain: "ocean",
      blurb: "The European Marine Observation and Data Network — harmonized bathymetry, chemistry, biology, geology, and human-activity layers for EU seas.",
      scale: "Pan-European", cadence: "periodic", access: ["API", "Bulk"], format: "netCDF, GeoTIFF",
    },
    {
      name: "GEBCO Bathymetry", url: "https://www.gebco.net/", domain: "ocean",
      blurb: "The reference global terrain model of the seafloor — a continuous gridded depth map of the entire ocean, updated annually.",
      scale: "15-arc-second global grid", cadence: "periodic", access: ["Bulk"], format: "netCDF, GeoTIFF",
      note: "The depth basemap under most dive and bathymetry maps.",
    },
    {
      name: "Allen Coral Atlas", url: "https://allencoralatlas.org/", domain: "ocean",
      blurb: "Satellite-derived maps of the world's shallow coral reefs — benthic composition, geomorphology, and a turbidity/bleaching monitoring system.",
      scale: "Global shallow reefs", cadence: "periodic", access: ["Bulk", "Web"], format: "GeoTIFF, Shapefile",
    },
    {
      name: "iNaturalist", url: "https://www.inaturalist.org/", domain: "ocean",
      blurb: "Citizen-science species observations (including reef and marine life) with photos — research-grade records flow into GBIF and an AWS open-data mirror.",
      scale: "200M+ observations", cadence: "live", access: ["API", "Bulk", "Cloud"], format: "CSV, JSON",
      note: "The open-images export is a popular training set for species-ID models.",
    },
    {
      name: "Marine Regions", url: "https://www.marineregions.org/", domain: "ocean",
      blurb: "The standard gazetteer of maritime boundaries and named sea areas (EEZs, IHO seas) — the geographic backbone for joining ocean datasets.",
      scale: "Global boundaries", cadence: "periodic", access: ["API", "Bulk"], format: "Shapefile, GeoJSON",
    },

    // ── Government & Economy ────────────────────────────────────────────────
    {
      name: "FRED (St. Louis Fed)", url: "https://fred.stlouisfed.org/", domain: "gov",
      blurb: "800k+ economic time series — rates, prices, employment, output — with the cleanest API in macro and one-call charting.",
      scale: "800k+ series", cadence: "daily", access: ["API", "Bulk"], format: "CSV, JSON",
      note: "The `fredapi` / `pandas-datareader` path is the fastest macro pull there is.",
    },
    {
      name: "World Bank Open Data", url: "https://data.worldbank.org/", domain: "gov",
      blurb: "World Development Indicators — thousands of country-year series on growth, health, education, and infrastructure, free and API-first.",
      scale: "16k+ indicators · 200+ countries", cadence: "periodic", access: ["API", "Bulk"], format: "CSV, JSON, XML",
    },
    {
      name: "IMF Data", url: "https://www.imf.org/en/Data", domain: "gov",
      blurb: "Cross-country macro and financial statistics — balance of payments, government finance, IFS — served via an SDMX API.",
      scale: "Global macro", cadence: "periodic", access: ["API", "Bulk"], format: "SDMX, CSV",
    },
    {
      name: "US Census Bureau", url: "https://data.census.gov/", domain: "gov",
      blurb: "American demographic and economic ground truth — ACS, decennial census, and business statistics down to the block-group level.",
      scale: "Billions of cells", cadence: "periodic", access: ["API", "Bulk"], format: "CSV, JSON",
    },
    {
      name: "Eurostat", url: "https://ec.europa.eu/eurostat/", domain: "gov",
      blurb: "The EU's official statistics — harmonized across member states for economy, population, trade, and environment, with a full API.",
      scale: "Thousands of datasets", cadence: "live", access: ["API", "Bulk"], format: "SDMX, TSV",
    },
    {
      name: "OECD Data Explorer", url: "https://data-explorer.oecd.org/", domain: "gov",
      blurb: "Comparable indicators across rich economies — productivity, inequality, health, and environment — on a modern SDMX backend.",
      scale: "Cross-country panels", cadence: "periodic", access: ["API", "Bulk"], format: "SDMX, CSV",
    },
    {
      name: "US BLS", url: "https://www.bls.gov/data/", domain: "gov",
      blurb: "The source for US labor and price data — CPI, the monthly jobs report, wages — with a registered public API.",
      scale: "Thousands of series", cadence: "periodic", access: ["API", "Bulk"], format: "JSON, CSV",
    },
    {
      name: "data.europa.eu", url: "https://data.europa.eu/", domain: "gov",
      blurb: "The official portal for European open data, aggregating national and EU-institution catalogs into one searchable index.",
      scale: "1.7M+ datasets", cadence: "live", access: ["API", "Bulk"], format: "Many",
    },

    // ── World, Society & Climate ────────────────────────────────────────────
    {
      name: "Our World in Data", url: "https://ourworldindata.org/", domain: "world",
      blurb: "Curated, long-run global indicators — emissions, energy, health, poverty — every chart backed by a clean, downloadable, well-sourced CSV.",
      scale: "Thousands of curated series", cadence: "live", access: ["Bulk", "API"], format: "CSV",
      note: "Datasets live on GitHub — stable URLs you can pull straight into pandas.",
    },
    {
      name: "GDELT Project", url: "https://www.gdeltproject.org/", domain: "world",
      blurb: "The Global Database of Events, Language & Tone — world news machine-coded into events, actors, and sentiment, refreshed every 15 minutes.",
      scale: "Updated every 15 min", cadence: "live", access: ["Query", "Bulk"], format: "CSV, BigQuery",
      note: "Queryable for free in BigQuery — a real-time pulse of global events.",
    },
    {
      name: "OpenStreetMap", url: "https://planet.openstreetmap.org/", domain: "world",
      blurb: "The full crowd-sourced map of the planet — every road, coastline, dive site, and building — available as a weekly planet dump.",
      scale: "~100 GB+ (planet, PBF)", cadence: "dump", access: ["Bulk", "API"], format: "OSM PBF, XML",
      note: "Geofabrik serves trimmed regional extracts so you skip the planet file.",
    },
    {
      name: "Copernicus Climate Data Store", url: "https://cds.climate.copernicus.eu/", domain: "world",
      blurb: "The home of ERA5 — hourly global atmospheric reanalysis back to 1940 — plus seasonal forecasts and climate-impact indicators, via API.",
      scale: "PB-scale reanalysis", cadence: "daily", access: ["API", "Bulk"], format: "netCDF, GRIB",
    },
    {
      name: "Berkeley Earth", url: "https://berkeleyearth.org/data/", domain: "world",
      blurb: "An independent, transparent global land+ocean temperature record — gridded and station-level, widely used for climate analysis.",
      scale: "1850→present", cadence: "periodic", access: ["Bulk"], format: "CSV, netCDF",
    },
    {
      name: "WHO Global Health Observatory", url: "https://www.who.int/data/gho", domain: "world",
      blurb: "The WHO's global health statistics — mortality, disease burden, risk factors, and health-system indicators — with an OData API.",
      scale: "1000+ indicators", cadence: "periodic", access: ["API", "Bulk"], format: "CSV, JSON",
    },
    {
      name: "Humanitarian Data Exchange", url: "https://data.humdata.org/", domain: "world",
      blurb: "OCHA's open platform for crisis and humanitarian data — population, displacement, food security, and conflict, standardized for rapid response.",
      scale: "20k+ datasets", cadence: "live", access: ["API", "Bulk"], format: "CSV, GeoJSON",
    },

    // ── Finance & Markets ───────────────────────────────────────────────────
    {
      name: "SEC EDGAR", url: "https://www.sec.gov/edgar/searchedgar/companysearch", domain: "finance",
      blurb: "Every US public-company filing — 10-Ks, 8-Ks, insider trades — as full text and structured XBRL financials, with bulk archives and a JSON API.",
      scale: "Millions of filings", cadence: "live", access: ["API", "Bulk"], format: "XBRL, HTML, JSON",
      note: "`companyfacts` JSON gives every reported financial concept per company.",
    },
    {
      name: "Nasdaq Data Link", url: "https://data.nasdaq.com/", domain: "finance",
      blurb: "The former Quandl — a unified API over many financial and economic datasets, mixing free and premium feeds behind one client.",
      scale: "Thousands of datasets", cadence: "daily", access: ["API", "Bulk"], format: "CSV, JSON",
    },
    {
      name: "Crypto on-chain (BigQuery)", url: "https://console.cloud.google.com/marketplace/product/bigquery-public-data/crypto-bitcoin", domain: "finance",
      blurb: "Full Bitcoin and Ethereum ledgers as Google BigQuery public datasets — every block, transaction, and trace, queryable in SQL.",
      scale: "Full chain history", cadence: "daily", access: ["Query", "Cloud"], format: "BigQuery",
    },
    {
      name: "Dune Analytics", url: "https://dune.com/", domain: "finance",
      blurb: "Decoded on-chain crypto data across dozens of blockchains, queryable in SQL with a public API — the standard for DeFi and NFT analytics.",
      scale: "Multi-chain", cadence: "live", access: ["API", "Query"], format: "SQL, CSV",
    },
    {
      name: "CFTC Commitments of Traders", url: "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", domain: "finance",
      blurb: "Weekly positioning of large traders across futures markets — the classic dataset for gauging speculative vs. commercial sentiment.",
      scale: "Weekly, all futures", cadence: "periodic", access: ["Bulk", "API"], format: "CSV",
    },
    {
      name: "Polymarket", url: "https://polymarket.com/", domain: "finance",
      blurb: "The largest prediction market — live prices and trade history as crowd-sourced probabilities on real-world events, via a public API and subgraph.",
      scale: "All markets + trades", cadence: "live", access: ["API", "Query"], format: "JSON, GraphQL",
      note: "Order-book and trade history make it a rich behavioral / forecasting dataset.",
    },
  ],
};

if (typeof window !== "undefined") window.REGISTRY_DATA = REGISTRY_DATA;
