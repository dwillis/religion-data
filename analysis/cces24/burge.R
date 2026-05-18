library(dplyr)
library(stringr)

cces <- cces %>% 
  filter(year >= 2022) %>% 
  mutate(
    trad = frcode(
      baptist == 1 ~ "Southern Baptist",
      baptist == 2 ~ "ABCUSA",
      baptist == 3 ~ "Natl. Baptist Convention",
      baptist == 4 ~ "Progressive Baptist Convention",
      baptist == 5 ~ "Independent Baptist",
      baptist == 6 ~ "Baptist General Conference",
      baptist == 7 ~ "Baptist Miss. Association",
      baptist == 8 ~ "Conservative Bapt. Association", 
      baptist == 9 ~ "Free Will Baptist",
      baptist == 10 ~ "Gen. Assoc. of Reg. Bapt.",
      baptist == 90 ~ "Other Baptist",
      methodist == 1 ~ "United Methodist",
      methodist == 2 ~ "Free Methodist",
      methodist == 3 ~ "African Methodist Episcopal",
      methodist == 4 ~ "AME - Zion",
      methodist == 5 ~ "Christian Methodist Episcopal",
      methodist == 90 ~ "Other Methodist",
      nondenom == 1 ~ "Nondenom Evangelical",
      nondenom == 2 ~ "Nondenom Fundamentalist",
      nondenom == 3 ~ "Nondenom Charismatic",
      nondenom == 4 ~ "Interdenominational",
      nondenom == 5 ~ "Community Church",
      nondenom == 90 ~ "Other Nondenom",
      lutheran == 1 ~ "ELCA",
      lutheran == 2 ~ "Lutheran - Missouri Synod",
      lutheran == 3 ~ "Lutheran - Wisconsin Synod",
      lutheran == 4 ~ "Other Lutheran",
      presbyterian == 1 ~ "PCUSA",
      presbyterian == 2 ~ "PCA",
      presbyterian == 3 ~ "Associated Reformed Presbyterian",
      presbyterian == 4 ~ "Cumberland Presbyterian", 
      presbyterian == 5 ~ "Orthodox Presbyterian",
      presbyterian == 6 ~ "Evangelical Presbyterian",
      presbyterian == 90 ~ "Other Presbyterian",
      pentecostal == 1 ~ "Assemblies of God",
      pentecostal == 2 ~ "Church of God Cleveland TN",
      pentecostal == 3 ~ "Four Square Gospel", 
      pentecostal == 4 ~ "Pentecostal Church of God",
      pentecostal == 5 ~ "Pentecostal Holiness Church",
      pentecostal == 6 ~ "Church of God in Christ",
      pentecostal == 7 ~ "Church of God of the Apostolic Faith",
      pentecostal == 8 ~ "Assembly of Christian Churches",
      pentecostal == 9 ~ "Apostolic Christian",
      pentecostal == 90 ~ "Other Pentecostal",
      episcopal == 1 ~ "TEC",
      episcopal == 2 ~ "Church of England",
      episcopal == 3 ~ "Anglican Orthodox",
      episcopal == 4 ~ "Reformed Episcopal",
      episcopal == 90 ~ "Other Episcopal",
      christian == 1 ~ "Church of Christ",
      christian == 2 ~ "Disciples of Christ",
      christian == 3 ~ "Christian Church",
      christian == 90 ~ "Other Christian Church",
      congregational == 1 ~ "United Church of Christ",
      congregational == 2 ~ "Conservative Cong. Christian",
      congregational == 3 ~ "National Assoc. of Cons. Cong.",
      congregational == 90 ~ "Other Cong.",
      holiness == 1 ~ "Church of the Nazarene",
      holiness == 2 ~ "Wesleyan Church",
      holiness == 4 ~ "Christian and Missionary Alliance",
      holiness == 5 ~ "Church of God",
      holiness == 6 ~ "Salvation Army",
      reformed == 1 ~ "Reformed Church in America",
      reformed == 2 ~ "Christian Reformed",
      reformed == 90 ~ "Other Reformed",
      adventist == 1 ~ "Seventh Day Adventist"
    )
  ) 


library(dplyr)
library(stringr)
library(forcats)
library(ggplot2)
library(scales)

# -- After creating `trad` variable --

top20 <- cces %>% 
  filter(year >= 2022) %>% 
  mutate(age = 2024 - birthyr) %>% 
  ct(trad) %>% 
  filter(!is.na(trad)) %>% 
  filter(!str_detect(trad, "^Other")) %>% 
  arrange(desc(n)) %>% 
  slice_head(n = 20) %>% 
  pull(trad)



cces_age <- cces %>%
  filter(year >= 2022) %>%
  mutate(
    age = 2024 - birthyr,
    age_bucket = cut(
      age,
      breaks = c(18, 30, 45, 60, 75, Inf),
      labels = c("18–29", "30–44", "45–59", "60–74", "75+"),
      right = FALSE
    )
  ) %>%
  filter(trad %in% top20)


age_dist <- cces_age %>%
  group_by(trad, age_bucket) %>%
  summarise(n = n(), .groups = "drop") %>%
  group_by(trad) %>%
  mutate(pct = n / sum(n)) %>%
  ungroup() %>%
  # reorder denominations by pct of 75+ (highest first)
  group_by(trad) %>%
  mutate(pct75 = pct[age_bucket == "75+"]) %>%
  ungroup() %>%
  mutate(trad = fct_reorder(trad, pct75))




ggplot(age_dist, aes(x = trad, y = pct, fill = fct_rev(age_bucket))) +
  geom_col(color = "black") +
  geom_text(
    aes(label = scales::percent(pct, accuracy = 1)),
    position = position_stack(vjust = 0.5),
    size = 3,
    family = "body",
    color = "black"
  ) +
  coord_flip() +
  scale_y_continuous(labels = percent_format()) +
  scale_fill_brewer(type = "qual", palette = "Set2") +
  guides(fill = guide_legend(reverse = TRUE)) +
  labs(
    title = "Age Distribution of the Top 20 Denominations",
    caption = "@ryanburge | Data: Cooperative Election Study 2022-2024",
    x = "",
    y = "Percent of Group",
    fill = "Age Bucket"
  ) +
  theme_rb() +
  theme(
    legend.position = "bottom",
    legend.text = element_text(size = 14),
    axis.text.y = element_text(size = 12),
    axis.text.x = element_text(size = 12)
  )

save("age_dist_top20.png")


age_stats <- cces %>%
  filter(year >= 2022, trad %in% top20) %>%
  mutate(age = 2024 - birthyr) %>%
  filter(!is.na(age)) %>%
  group_by(trad) %>%
  summarise(
    mean_age = mean(age, na.rm = TRUE),
    # simple mode: pick the age with the largest count
    mode_age = {
      tab <- table(age)
      as.numeric(names(tab)[which.max(tab)])
    },
    n = n(),
    .groups = "drop"
  ) %>%
  # order denominations by mean age (oldest at the top in the plot)
  mutate(trad = fct_reorder(trad, mean_age))


age_stats_long <- age_stats %>%
  select(trad, mean_age, mode_age) %>%
  pivot_longer(
    cols = c(mean_age, mode_age),
    names_to = "stat",
    values_to = "age"
  )




library(ggplot2)




ggplot(age_stats, aes(y = trad)) +
  # grey line between mode and mean (dumbbell)
  geom_segment(
    aes(x = mode_age, xend = mean_age, yend = trad),
    color = "grey60",
    linewidth = 0.6
  ) +
  # points for mode + mean
  geom_point(
    data = age_stats_long,
    aes(x = age, color = stat),
    size = 3
  ) +
  # labels above points
  geom_text(
    data = age_stats_long,
    aes(x = age, label = round(age, 0), color = stat),
    vjust = -0.8,
    size = 3,
    family = "font", show.legend = FALSE
  ) +
  scale_color_manual(
    values = c("mean_age" = "#d73027",   # red
               "mode_age" = "#4575b4"),  # blue
    labels = c("Mean age", "Mode age"),
    name   = ""
  ) +
  labs(
    title = "Mean and Mode Age by Denomination",
    caption = "@ryanburge | Data: Cooperative Election Study, 2022-2024",
    x = "Age",
    y = ""
  ) +
  theme_rb() +
  theme(
    legend.position = "bottom",
    axis.text.y = element_text(size = 12),
    axis.text.x = element_text(size = 12)
  )

save("mean_mode_age.png")


library(ggplot2)
library(ggbeeswarm)
library(stringr)
library(Polychrome)

cces_bees <- cces %>%
  filter(year >= 2022, trad %in% top20) %>%
  mutate(
    age  = 2024 - birthyr,
    trad = factor(trad, levels = top20)   # <-- IMPORTANT
  ) %>%
  filter(!is.na(age))


library(Polychrome)

pal20 <- palette36.colors(length(top20))
names(pal20) <- top20


# compute mode ages
mode_age_df <- cces_bees %>%
  group_by(trad) %>%
  summarise(
    mode_age = {
      tab <- table(age)
      as.numeric(names(tab)[which.max(tab)])
    }
  )

# reorder trad so oldest mode is first (top-left facet)
cces_bees <- cces_bees %>%
  left_join(mode_age_df, by = "trad") %>%
  mutate(trad = fct_reorder(trad, mode_age, .desc = TRUE))

cces_bees <- cces_bees %>%
  mutate(
    trad = fct_recode(
      trad,
      "Interdenom." = "Interdenominational"
    )
  )

mode_age_df <- mode_age_df %>%
  mutate(
    trad = fct_recode(
      trad,
      "Interdenom." = "Interdenominational"
    )
  )


ggplot(cces_bees, aes(x = 1, y = age, color = trad)) +
  # beeswarm
  geom_quasirandom(
    alpha = 0.65,
    size  = 1,
    width = 0.25
  ) +
  # widest-point (mode) line per facet
  geom_hline(
    data = mode_age_df,
    aes(yintercept = mode_age),
    color = "black",
    linewidth = 1
  ) +
  facet_wrap(
    ~ trad,
    nrow = 2,
    labeller = labeller(trad = ~ stringr::str_wrap(.x, width = 15))
  ) +
  scale_color_manual(values = pal20) +
  labs(
    title = "Age Distribution by Denomination",
    caption = "@ryanburge | Data: Cooperative Election Study 2022-2024",
    x = "",
    y = "Age"
  ) +
  theme_rb() +
  theme(
    legend.position   = "none",
    axis.text.x       = element_blank(),
    axis.ticks.x      = element_blank(),
    strip.text        = element_text(size = 11, face = "bold", lineheight = 1.1)
  )


save("swarms_age_top20.png", wd = 10, ht = 10)



cces <- cces %>% 
  mutate(
    trad = frcode(
      baptist == 1 ~ "Southern Baptist",
      baptist == 2 ~ "ABCUSA",
      baptist == 3 ~ "Natl. Baptist Convention",
      baptist == 4 ~ "Progressive Baptist Convention",
      baptist == 5 ~ "Independent Baptist",
      baptist == 6 ~ "Baptist General Conference",
      baptist == 7 ~ "Baptist Miss. Association",
      baptist == 8 ~ "Conservative Bapt. Association", 
      baptist == 9 ~ "Free Will Baptist",
      baptist == 10 ~ "Gen. Assoc. of Reg. Bapt.",
      baptist == 90 ~ "Other Baptist",
      methodist == 1 ~ "United Methodist",
      methodist == 2 ~ "Free Methodist",
      methodist == 3 ~ "African Methodist Episcopal",
      methodist == 4 ~ "AME - Zion",
      methodist == 5 ~ "Christian Methodist Episcopal",
      methodist == 90 ~ "Other Methodist",
      nondenom == 1 ~ "Nondenom Evangelical",
      nondenom == 2 ~ "Nondenom Fundamentalist",
      nondenom == 3 ~ "Nondenom Charismatic",
      nondenom == 4 ~ "Interdenominational",
      nondenom == 5 ~ "Community Church",
      nondenom == 90 ~ "Other Nondenom",
      lutheran == 1 ~ "ELCA",
      lutheran == 2 ~ "Lutheran - Missouri Synod",
      lutheran == 3 ~ "Lutheran - Wisconsin Synod",
      lutheran == 4 ~ "Other Lutheran",
      presbyterian == 1 ~ "PCUSA",
      presbyterian == 2 ~ "PCA",
      presbyterian == 3 ~ "Associated Reformed Presbyterian",
      presbyterian == 4 ~ "Cumberland Presbyterian", 
      presbyterian == 5 ~ "Orthodox Presbyterian",
      presbyterian == 6 ~ "Evangelical Presbyterian",
      presbyterian == 90 ~ "Other Presbyterian",
      pentecostal == 1 ~ "Assemblies of God",
      pentecostal == 2 ~ "Church of God Cleveland TN",
      pentecostal == 3 ~ "Four Square Gospel", 
      pentecostal == 4 ~ "Pentecostal Church of God",
      pentecostal == 5 ~ "Pentecostal Holiness Church",
      pentecostal == 6 ~ "Church of God in Christ",
      pentecostal == 7 ~ "Church of God of the Apostolic Faith",
      pentecostal == 8 ~ "Assembly of Christian Churches",
      pentecostal == 9 ~ "Apostolic Christian",
      pentecostal == 90 ~ "Other Pentecostal",
      episcopal == 1 ~ "TEC",
      episcopal == 2 ~ "Church of England",
      episcopal == 3 ~ "Anglican Orthodox",
      episcopal == 4 ~ "Reformed Episcopal",
      episcopal == 90 ~ "Other Episcopal",
      christian == 1 ~ "Church of Christ",
      christian == 2 ~ "Disciples of Christ",
      christian == 3 ~ "Christian Church",
      christian == 90 ~ "Other Christian Church",
      congregational == 1 ~ "United Church of Christ",
      congregational == 2 ~ "Conservative Cong. Christian",
      congregational == 3 ~ "National Assoc. of Cons. Cong.",
      congregational == 90 ~ "Other Cong.",
      holiness == 1 ~ "Church of the Nazarene",
      holiness == 2 ~ "Wesleyan Church",
      holiness == 4 ~ "Christian and Missionary Alliance",
      holiness == 5 ~ "Church of God",
      holiness == 6 ~ "Salvation Army",
      reformed == 1 ~ "Reformed Church in America",
      reformed == 2 ~ "Christian Reformed",
      reformed == 90 ~ "Other Reformed",
      adventist == 1 ~ "Seventh Day Adventist"
    )
  )


cces <- read.fst("E://data/full_cces24.fst")


cces <- cces %>% 
  mutate(
    trad = frcode(
      baptist == 1 ~ "Southern Baptist",
      baptist == 2 ~ "ABCUSA",
      baptist == 3 ~ "Natl. Baptist Convention",
      baptist == 4 ~ "Progressive Baptist Convention",
      baptist == 5 ~ "Independent Baptist",
      baptist == 6 ~ "Baptist General Conference",
      baptist == 7 ~ "Baptist Miss. Association",
      baptist == 8 ~ "Conservative Bapt. Association", 
      baptist == 9 ~ "Free Will Baptist",
      baptist == 10 ~ "Gen. Assoc. of Reg. Bapt.",
      baptist == 90 ~ "Other Baptist",
      methodist == 1 ~ "United Methodist",
      methodist == 2 ~ "Free Methodist",
      methodist == 3 ~ "African Methodist Episcopal",
      methodist == 4 ~ "AME - Zion",
      methodist == 5 ~ "Christian Methodist Episcopal",
      methodist == 90 ~ "Other Methodist",
      nondenom == 1 ~ "Nondenom Evangelical",
      nondenom == 2 ~ "Nondenom Fundamentalist",
      nondenom == 3 ~ "Nondenom Charismatic",
      nondenom == 4 ~ "Interdenominational",
      nondenom == 5 ~ "Community Church",
      nondenom == 90 ~ "Other Nondenom",
      lutheran == 1 ~ "ELCA",
      lutheran == 2 ~ "Lutheran - Missouri Synod",
      lutheran == 3 ~ "Lutheran - Wisconsin Synod",
      lutheran == 4 ~ "Other Lutheran",
      presbyterian == 1 ~ "PCUSA",
      presbyterian == 2 ~ "PCA",
      presbyterian == 3 ~ "Associated Reformed Presbyterian",
      presbyterian == 4 ~ "Cumberland Presbyterian", 
      presbyterian == 5 ~ "Orthodox Presbyterian",
      presbyterian == 6 ~ "Evangelical Presbyterian",
      presbyterian == 90 ~ "Other Presbyterian",
      pentecostal == 1 ~ "Assemblies of God",
      pentecostal == 2 ~ "Church of God Cleveland TN",
      pentecostal == 3 ~ "Four Square Gospel", 
      pentecostal == 4 ~ "Pentecostal Church of God",
      pentecostal == 5 ~ "Pentecostal Holiness Church",
      pentecostal == 6 ~ "Church of God in Christ",
      pentecostal == 7 ~ "Church of God of the Apostolic Faith",
      pentecostal == 8 ~ "Assembly of Christian Churches",
      pentecostal == 9 ~ "Apostolic Christian",
      pentecostal == 90 ~ "Other Pentecostal",
      episcopal == 1 ~ "TEC",
      episcopal == 2 ~ "Church of England",
      episcopal == 3 ~ "Anglican Orthodox",
      episcopal == 4 ~ "Reformed Episcopal",
      episcopal == 90 ~ "Other Episcopal",
      christian == 1 ~ "Church of Christ",
      christian == 2 ~ "Disciples of Christ",
      christian == 3 ~ "Christian Church",
      christian == 90 ~ "Other Christian Church",
      congregational == 1 ~ "United Church of Christ",
      congregational == 2 ~ "Conservative Cong. Christian",
      congregational == 3 ~ "National Assoc. of Cons. Cong.",
      congregational == 90 ~ "Other Cong.",
      holiness == 1 ~ "Church of the Nazarene",
      holiness == 2 ~ "Wesleyan Church",
      holiness == 4 ~ "Christian and Missionary Alliance",
      holiness == 5 ~ "Church of God",
      holiness == 6 ~ "Salvation Army",
      reformed == 1 ~ "Reformed Church in America",
      reformed == 2 ~ "Christian Reformed",
      reformed == 90 ~ "Other Reformed",
      adventist == 1 ~ "Seventh Day Adventist"
    )
  )


share_18_40 <- cces %>%
  mutate(
    age = year - birthyr,
    period = case_when(
      year %in% 2008:2010 ~ "2008–2010",
      year %in% 2022:2024 ~ "2022–2024",
      TRUE ~ NA_character_
    )
  ) %>%
  filter(
    !is.na(period),
    trad %in% top20,
    age >= 18, age <= 100
  ) %>%
  group_by(period, trad) %>%
  summarise(
    pct_18_40 = weighted.mean(age <= 40, w = weight, na.rm = TRUE),
    n_eff     = sum(!is.na(age)),
    .groups = "drop"
  ) %>%
  arrange(period, desc(pct_18_40))



library(dplyr)
library(forcats)
library(ggplot2)
library(scales)
library(stringr)

# 1) Make period an ordered factor, and order trad by 2022–2024 pct_18_40
plot_df <- share_18_40 %>%
  mutate(period = factor(period, levels = c("2008–2010", "2022–2024"))) 

# order denominations by 2022–2024 share of 18–40 (highest first)
trad_order <- plot_df %>%
  filter(period == "2022–2024") %>%
  arrange(desc(pct_18_40)) %>%
  pull(trad)

plot_df <- plot_df %>%
  mutate(
    trad = factor(trad, levels = trad_order),
    trad_lab = str_wrap(as.character(trad), width = 18)  # wrapped labels for facets
  )

# 2) Faceted bar chart: two bars per trad
ggplot(plot_df, aes(x = period, y = pct_18_40, fill = period)) +
  geom_col(color = "black") +
  geom_text(
    aes(label = scales::percent(pct_18_40, accuracy = 1)),
    vjust = -0.3,
    size = 6,
    family = "bold"
  ) +
  facet_wrap(~ trad_lab, nrow = 4) +
  scale_y_continuous(labels = percent_format(), limits = c(0, 0.55)) +
  scale_fill_manual(
    values = c("2008–2010" = "#4575b4",  # blue
               "2022–2024" = "#d73027")  # red
  ) +
  labs(
    title = "Share of Each Denomination That Is Age 18–40",
    caption = "@ryanburge | Data: Cooperative Election Study, 2022-2024",
    x = "",
    y = "",
    fill = ""
  ) +
  theme_rb() +
  theme(
    legend.position = "none",
    strip.text = element_text(size = 10, family = "font", lineheight = 1.1),
    axis.text.x = element_text(size = 9),
    axis.text.y = element_text(size = 9)
  )

# optional save
save("bars_18_40_facet_top20.png", wd = 8, ht = 10)




cces_2224 <- cces %>%
  filter(year %in% 2022:2024,
         trad %in% top20) %>%
  mutate(
    age = year - birthyr,
    age = pmin(pmax(age, 18), 100),         # keep it sane
    years_left = pmax(0, 85 - age)         # assuming everyone dead by 85
  )




library(Hmisc)

death_quants <- cces_2224 %>%
  group_by(trad) %>%
  summarise(
    years_30 = as.numeric(
      wtd.quantile(years_left, weights = weight, probs = 0.30, na.rm = TRUE)
    ),
    years_40 = as.numeric(
      wtd.quantile(years_left, weights = weight, probs = 0.40, na.rm = TRUE)
    ),
    years_50 = as.numeric(
      wtd.quantile(years_left, weights = weight, probs = 0.50, na.rm = TRUE)
    ),
    .groups = "drop"
  ) %>%
  mutate(
    year_30 = 2024 + years_30,
    year_40 = 2024 + years_40,
    year_50 = 2024 + years_50
  )



library(dplyr)
library(tidyr)
library(forcats)
library(ggplot2)

# death_quants as you printed it:
# columns: trad, years_30, years_40, years_50, year_30, year_40, year_50

# 1) order traditions: which groups hit 50% dead the soonest (oldest at top)
trad_order <- death_quants %>%
  arrange(years_50) %>%          # smaller years_50 = sooner 50% dead
  pull(trad)

death_quants <- death_quants %>%
  mutate(trad = factor(trad, levels = trad_order))




death_years_long <- death_quants %>%
  select(trad, year_30, year_40, year_50) %>%
  pivot_longer(
    cols = starts_with("year_"),
    names_to = "threshold",
    values_to = "death_year"
  ) %>%
  mutate(
    threshold = dplyr::recode(threshold,
                       "year_30" = "30%",
                       "year_40" = "40%",
                       "year_50" = "50%"),
    threshold = factor(threshold, levels = c("30%", "40%", "50%"))
  )


trad_order <- death_quants %>%
  arrange(year_50) %>%      # earliest median death year first
  pull(trad)

death_years_long <- death_years_long %>%
  mutate(trad = factor(trad, levels = trad_order))



library(ggplot2)

ggplot() +
  # Line connecting 30% → 50% death years
  geom_segment(
    data = death_quants,
    aes(x = year_30, xend = year_50, y = trad, yend = trad),
    color = "grey75",
    linewidth = 1.2
  ) +
  # Points at 30%, 40%, 50%
  geom_point(
    data = death_years_long,
    aes(x = death_year, y = trad, color = threshold),
    size = 3
  ) +
  # Numeric labels above points
  geom_text(
    data = death_years_long,
    aes(x = death_year, y = trad, label = round(death_year), color = threshold),
    vjust = -0.7,
    size = 3,
    family = "font", show.legend = FALSE
  ) +
  scale_color_manual(
    values = c("30%" = "#4575b4",   # blue
               "40%" = "#fdae61",   # orange
               "50%" = "#d73027"),  # red
    name = "Share of current adults who have died"
  ) +
  scale_x_continuous(
    breaks = seq(2030, 2075, by = 5),
    expand = expansion(mult = c(0.02, 0.08))
  ) +
  labs(
    title = "When Will Today’s Adults Be Gone?",
    subtitle = "Assuming That All Adults Live to 85 Years Old",
    caption = "@ryanburge | Data: Cooperative Election Study, 2022-2024", 
    x = "Calendar Year",
    y = ""
  ) +
  theme_rb() +
  theme(
    legend.position = "bottom",
    legend.text = element_text(size = 20), 
    axis.text.y = element_text(size = 11),
    axis.text.x = element_text(size = 10)
  )

save("death_timeline_calendar_years.png", wd = 10, ht = 7)



boomers <- cces %>%
  filter(year %in% 2022:2024,
         trad %in% top20) %>%
  mutate(
    age = year - birthyr,
    boomer = if_else(birthyr >= 1946 & birthyr <= 1964, 1, 0, missing = 0)
  ) %>%
  filter(age >= 18, age <= 100) %>%
  group_by(trad) %>%
  summarise(
    pct_boomer = weighted.mean(boomer, w = weight, na.rm = TRUE),
    n_eff      = sum(!is.na(age)),
    .groups = "drop"
  )

# 🔑 Order for plotting: lowest at bottom, highest at top
boomers_plot <- boomers %>%
  arrange(pct_boomer) %>%                 # ascending
  mutate(trad = factor(trad, levels = trad))  # lock that order in



ggplot(boomers_plot, aes(x = trad, y = pct_boomer, fill = trad)) +
  geom_col(color = "black") +
  coord_flip() +
  geom_text(
    aes(label = scales::percent(pct_boomer, accuracy = 1)),
    hjust = -0.17,
    size = 5,
    family = "bold"
  ) +
  scale_y_continuous(
    labels = scales::percent_format(),
    limits = c(0, max(boomers_plot$pct_boomer) * 1.12)
  ) +
  scale_fill_manual(values = pal20) +
  labs(
    title = "Share of Each Denomination’s Adults Who Are Baby Boomers",
    caption = "@ryanburge | Data: Cooperative Election Study, 2022-2024", 
    x = "",
    y = ""
  ) +
  theme_rb() +
  theme(
    legend.position = "none",
    axis.text.y = element_text(size = 11),
    axis.text.x = element_text(size = 10)
  )



# optional
save("boomers_share_top20.png", wd = 9, ht = 7)


