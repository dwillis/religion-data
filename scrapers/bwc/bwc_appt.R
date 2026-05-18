library(rvest)
library(dplyr)
library(stringr)

url <- "https://www.bwcumc.org/news/2026-appointments/"

page <- read_html(url)

content <- page |> html_element("div#text")

# Pull all relevant nodes: h6 date headers and li appointment items
nodes <- content |> html_elements("h6, ul > li")

appointments <- list()
current_date <- NA_character_

for (node in nodes) {
  tag <- html_name(node)

  if (tag == "h6") {
    current_date <- html_text(node, trim = TRUE)
    next
  }

  # li appointment entry
  raw_text <- html_text(node, trim = TRUE)

  # Extract clergy name from <strong> tag
  name <- node |> html_element("strong") |> html_text(trim = TRUE)
  name <- str_remove(name, ",$")

  # Remove the name portion from raw text to isolate the rest
  rest <- str_remove(raw_text, fixed(html_text(node |> html_element("strong"), trim = TRUE)))
  rest <- str_trim(rest)
  rest <- str_remove(rest, "^,\\s*")

  # Split on ", to " and ", from "
  to_part <- str_match(rest, "^to\\s+(.+?)(?:,\\s*from\\s+|$)")[, 2]
  from_part <- str_match(rest, "from\\s+(.+)$")[, 2]

  appointments[[length(appointments) + 1]] <- tibble(
    date       = current_date,
    name       = name,
    to         = str_trim(to_part),
    from       = str_trim(from_part)
  )
}

appts <- bind_rows(appointments)

cat(sprintf("Scraped %d appointments\n", nrow(appts)))
print(appts)
