# Downloadable U.S. Religion Census data for student replication in R

**Every wave of the U.S. Religion Census from 1952 through 2020 is freely downloadable**, and the 2020 release is the most accessible yet — with county-level Excel files requiring no registration at usreligioncensus.org and SPSS/Stata files at ARDA. Below are six specific data products and published analyses a student can download today and replicate in R, plus complementary census-based religion datasets that extend the analytical possibilities.

The U.S. Religion Census (formally the Religious Congregations & Membership Study, or RCMS) is the only recurring project that counts congregations and adherents by denomination at the county level across the entire United States. Conducted roughly every decade by the Association of Statisticians of American Religious Bodies (ASARB), the 2020 wave covers **372 religious bodies**, **356,739 congregations**, and **161.4 million adherents** (48.6% of the U.S. population). The data and all 11 analytical chapters of the official publication are free, making this an unusually rich resource for student projects.

---

## 1. The 2020 county-level Excel files are the easiest starting point

Two Excel workbooks at usreligioncensus.org contain the complete 2020 data and require **no registration or login** — just click and download:

- **Summary file** (`2020_USRC_Summaries.xlsx`): Worksheets for nation, state, county, and metro levels. Each row is a geographic unit; columns include total congregations, total adherents, adherents as a percentage of population, and congregations/adherents for broad religious families (Evangelical Protestant, Mainline Protestant, Black Protestant, Catholic, Orthodox, Other). Download at `usreligioncensus.org/sites/default/files/2023-06/2020_USRC_Summaries.xlsx`.

- **Group Detail file** (`2020_USRC_Group_Detail.xlsx`): Same geographic levels but with congregation and adherent counts for each of the **372 individual religious bodies**. Download at `usreligioncensus.org/sites/default/files/2023-06/2020_USRC_Group_Detail.xlsx`.

Both files were updated June 23, 2023 with minor corrections. A student can read these directly into R with `readxl::read_excel()` — no data format conversion needed. The county sheet uses FIPS codes, making merges with Census Bureau demographic data straightforward. A companion book-tables file (`2020_USRC_book_Tables_1-4.xlsx`) reproduces the four summary tables from the printed publication.

For students who prefer labeled statistical files, the **ARDA county file** (ID: `RCMSCY20`, at `thearda.com/data-archive?fid=RCMSCY20`) provides the same 2020 data in SPSS `.sav` format with variable labels, readable in R via `haven::read_sav()`. In January 2024, ARDA added **21 religious tradition (RELTRAD) variables** to this file, classifying groups into the Steensland et al. typology used across sociology of religion. A state-level file is also available (`RCMSST20`).

---

## 2. Six specific reports and data products students can replicate

### Report 1: Dale Jones's religious diversity chapter (2020 Census)

Chapter 6 of the 2020 publication, "Religious Diversity in the United States" by Dale E. Jones, computes **Shannon and Simpson diversity indexes** for every U.S. county, produces choropleth maps, and ranks states and counties by diversity. The free PDF is at `usreligioncensus.org/sites/default/files/2023-10/ReligiousDiversity-Jones.pdf`. A student would download the Group Detail Excel file, calculate the diversity indexes using the denomination-level adherent shares per county, and map results with `ggplot2` and `sf`. This is an ideal intermediate R exercise covering data reshaping, index calculation, and spatial visualization. **Difficulty: beginner to intermediate.**

### Report 2: Erica Dollhopf's 2010–2020 trends chapter

Chapter 4, "Trends in US Religion Census Adherents Data, 2010-2020" by Erica J. Dollhopf (PDF at `usreligioncensus.org/sites/default/files/2023-10/Trends2010to2020-Dollhopf.pdf`), analyzes change in adherent counts between 2010 and 2020 by denomination, religious family, and geography. Replication requires downloading both the 2020 county file and the 2010 county file from ARDA (`RCMSCY10`). Students merge the two files on FIPS code, compute percentage changes, and identify which groups grew or declined and where. This teaches **data merging, change calculation, and comparative visualization** — core data-wrangling skills.

### Report 3: Warf & Winsberg's "Geography of Religious Diversity" (2008)

Published in *The Professional Geographer* (Vol. 60, No. 3, pp. 413–424), this paper uses only the 2000 RCMS county file (ARDA ID: `RCMSCY`) to construct four diversity measures per county: number of denominations, proportion in the largest denomination, Shannon index, and Simpson index. It then maps the results as choropleth maps and Dorling cartograms, regresses denomination count against county population, and maps regression residuals. **Every input is freely downloadable.** A student could replicate the original analysis and then update it with 2010 or 2020 data to produce an original contribution. This is one of the most cited geographies-of-religion papers and is highly suitable for an undergraduate methods course. **Difficulty: intermediate.**

### Report 4: Bacon, Finke & Jones's longitudinal merged file (2018)

Their paper "Merging the Religious Congregations and Membership Studies" in *Review of Religious Research* (Vol. 60, pp. 358–386; free full text at `pmc.ncbi.nlm.nih.gov/articles/PMC6182411/`) documents exactly how they harmonized **four decades of RCMS data (1980–2010)** into a single longitudinal county file. The resulting merged file is freely downloadable from ARDA as `RCMSMGCY` at `thearda.com/data-archive?fid=RCMSMGCY`. It contains adherent and congregation counts for **302 religious groups** with corrections for mergers, schisms, changing membership definitions, and county boundary changes. A student can download this single file and immediately analyze denominational growth or decline trajectories across four decades at the county level — an exercise in **longitudinal analysis, data quality assessment, and trend visualization**. The paper itself serves as a codebook explaining every transformation, making it an excellent teaching tool about real-world data harmonization. **Difficulty: intermediate to advanced.**

### Report 5: Finke & Scheitle's "Accounting for the Uncounted" (2005)

Published in *Review of Religious Research* (Vol. 47, No. 1, pp. 5–22), this paper develops correction factors for systematic undercounting in the 2000 RCMS — particularly of historically Black denominations and groups that did not participate. Using only the freely available 2000 RCMS county file from ARDA plus Yearbook of American and Canadian Churches totals, the authors raise the estimated national adherence rate from **50% to 63%**. Students can replicate the correction methodology, apply it to the 2010 or 2020 data, and compare adjusted vs. unadjusted rates. This exercise teaches **critical thinking about data quality, measurement error, and statistical adjustment** — skills often absent from standard methods courses. **Difficulty: intermediate.**

### Report 6: Julia Silge's R mapping tutorial (2016)

This blog post at `arilamstein.com/blog/2016/01/25/mapping-us-religion-adherence-county-r/` provides **complete, copy-paste R code** for creating choropleth maps of 2010 RCMS county data using `choroplethr` and `ggplot2`. It walks through downloading data from ARDA, cleaning it, and producing maps of total adherence rates, Catholic adherence, LDS adherence, and evangelical Protestant adherence. It also discusses data quality anomalies (counties where adherents exceed population). This is the single most accessible starting point for students new to R — a **complete, tested tutorial** that can be updated to use 2020 data for a fresh project. **Difficulty: beginner.**

---

## 3. All previous waves remain fully accessible through ARDA

ARDA hosts county-level and state-level files for every wave of this project going back to 1952. The table below summarizes confirmed availability:

| Wave | County file ID | Religious bodies covered | Key notes |
|------|---------------|------------------------|-----------|
| 2020 | `RCMSCY20` | 372 | Also downloadable as Excel from usreligioncensus.org |
| 2010 | `RCMSCY10` | 236 | Also on GitHub via `rearc-data` repository in XLSX |
| 2000 | `RCMSCY` | 149 | Includes Finke & Scheitle adjusted adherence rates |
| 1990 | Browse Category B | 133 | Copyright: Glenmary Research Center |
| 1980 | `CMS80CNT` | 111 | Copyright: Glenmary Research Center |
| 1971 | Browse Category B | 53 | ~81% of U.S. church membership covered |
| 1952 | `CMS52CNT` | 114 | National Council of Churches collection |
| 1980–2010 merged | `RCMSMGCY` | 302 (harmonized) | Bacon, Finke & Jones longitudinal file |

All ARDA files are free with no registration — users simply agree to usage terms. Files download in **SPSS `.sav` and `.por` formats**, readable in R via `haven::read_sav()` or `foreign::read.spss()`. Codebooks with variable descriptions and frequency tables are available alongside each file. State-level versions exist for each wave (file IDs follow the pattern `RCMSST`, `RCMSST10`, `RCMSST20`).

---

## 4. Practical details for getting data into R

The most frictionless path is the **Excel route**: download the 2020 `.xlsx` files from usreligioncensus.org and read them with `readxl::read_excel()`, specifying the desired worksheet (nation, state, county, or metro). No account creation, no format conversion.

For ARDA's SPSS files, the workflow is:

```r
library(haven)
rcms <- read_sav("RCMSCY20.sav")  # preserves variable labels as attributes
```

Key variables across all waves include **FIPS county code** (for merging with Census data), **total congregations**, **total adherents**, **adherents as percentage of population**, and denomination-specific congregation and adherent counts. The 2020 file's RELTRAD variables classify each group into Evangelical Protestant, Mainline Protestant, Black Protestant, Catholic, Orthodox, Jewish, or Other — the standard typology in quantitative sociology of religion.

Missing data is typically coded as blank or `-9`. County FIPS codes are five-digit numeric. Students merging with American Community Survey data should confirm FIPS formatting matches (leading zeros can cause issues when read as numeric). The 2020 Excel files have **3,143 county-level rows** — one per county or county-equivalent.

---

## 5. Complementary census-based datasets worth knowing

Beyond RCMS, three other count-based (not survey-based) datasets with publicly downloadable data stand out for student projects:

**The American Religious Ecologies Project** (George Mason University, `religiousecologies.org/data/`) has digitized the federal Census of Religious Bodies from 1906, 1916, 1926, and 1936 and published cleaned **CSV files directly on GitHub**. These include denomination-level counts of organizations, edifices, seating capacity, property values, and members at the city level. The CSV-on-GitHub format is the most R-friendly option in this entire ecosystem. Students interested in long-run religious change can combine these files with the RCMS series to analyze trends spanning over a century.

**The historical Census of Religious Bodies** (1906–1936) is also available through ARDA and ICPSR at the county and state levels in SPSS/Stata format. These were actual federal government enumerations — the U.S. Census Bureau collected religion data until Congress defunded the effort after 1936. ARDA hosts these under Category B of its data archive (`thearda.com/data-archive/browse-categories?cid=B`).

**The National Congregations Study** (NCS, Duke University, Mark Chaves) is survey-based rather than count-based, but complements RCMS by measuring what congregations *do* rather than where they *are*. Four waves (1998, 2006, 2012, 2018) are freely available on ARDA (cumulative file: `NCSIV`, with **5,333 congregations and 1,083 variables** covering worship style, staffing, programs, social services, finances, and demographics). Available in SPSS, Stata, and R formats. While it cannot be analyzed geographically at the county level (sampling is national), it pairs well with RCMS for projects comparing institutional presence with congregational characteristics.

For capturing the religiously unaffiliated — which RCMS structurally cannot measure since "nones" have no institutional affiliation to report — the **PRRI Census of American Religion** (`prri.org`) uses Bayesian small-area estimation on ~500,000 pooled survey interviews to produce county-level estimates of religious identity including the unaffiliated. The interactive American Values Atlas tool at `ava.prri.org` allows county-level exploration, though bulk data downloads are more limited than ARDA's offerings.

---

## Conclusion: what makes this ecosystem unusually student-friendly

The U.S. Religion Census stands out among social science datasets for the combination of **free access, county-level granularity, seven decades of temporal coverage, and multiple download formats** — a rare alignment that removes most barriers to student replication. The six reports identified above span a range of analytical approaches (descriptive statistics, diversity indexes, regression, longitudinal harmonization, data quality correction, and spatial visualization) and difficulty levels (beginner through advanced), all grounded in the same freely downloadable data.

The most important practical insight is that **two parallel download paths exist**: the Excel files at usreligioncensus.org for zero-friction access, and the SPSS files at ARDA for richer metadata and variable labels. Students should start with the Excel path and the Julia Silge mapping tutorial, then graduate to ARDA's labeled files and the more analytically demanding papers. The ARDA's RELTRAD variables added to the 2020 file in January 2024 eliminate what was previously a significant recoding burden, making denominational-family analysis accessible to beginners for the first time. The longitudinal merged file (`RCMSMGCY`) is the single most powerful resource for ambitious projects, offering four harmonized decades of county-level data in one download — but students must read the Bacon, Finke & Jones paper before using it, as the file differs substantially from the standalone waves.