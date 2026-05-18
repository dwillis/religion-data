library(tidyverse)
library(rvest)
library(httr)

r <- GET("https://www.bwcumc.org/news/2026-appointments/",
         config(ssl_verifypeer = FALSE, http_version = 1))
html <- read_html(content(r, "text"))
text_div <- html |> html_element("#text")

nodes <- text_div |> html_children()

appointments <- list()
current_date <- NA

for (node in nodes) {
  tag <- html_name(node)

  if (tag == "h6") {
    current_date <- html_text(node, trim = TRUE)
  } else if (tag == "ul") {
    items <- node |> html_elements("li")
    for (item in items) {
      name <- item |> html_element("strong") |> html_text(trim = TRUE)
      full_text <- html_text(item, trim = TRUE)
      appointments <- append(appointments, list(data.frame(
        date = current_date,
        name = name,
        text = full_text,
        stringsAsFactors = FALSE
      )))
    }
  }
}

df <- bind_rows(appointments)
write_csv(df, "bwc_appointments_2026.csv")
cat(sprintf("Extracted %d appointments\n", nrow(df)))
