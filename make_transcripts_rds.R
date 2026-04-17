library(dplyr)

transcript_dir <- "transcripts"
files <- list.files(transcript_dir, pattern = "\\.txt$", full.names = TRUE)

clean_text <- function(txt) {
  # Remove speaker labels (e.g. "Speaker 1", "Speaker 2:")
  txt <- gsub("Speaker \\d+\\s*:?\\s*", "", txt)
  # Remove bracketed content [...]
  txt <- gsub("\\[.*?\\]", "", txt)
  # Remove parenthetical stage directions
  txt <- gsub("\\(.*?\\)", "", txt)
  # Remove musical notes
  txt <- gsub("\u266a", "", txt)
  # Remove hashtag-prefixed lyrics lines
  txt <- gsub("#[^\\n]*", "", txt)
  # Remove leading dashes/bullets
  txt <- gsub("^\\s*[-–—]\\s*", "", txt, perl = TRUE)
  # Collapse multiple spaces and newlines into single spaces
  txt <- gsub("\\s+", " ", txt)
  # Trim
  trimws(txt)
}

df <- tibble(
  source = basename(files),
  text   = sapply(files, function(f) {
    raw <- paste(readLines(f, warn = FALSE), collapse = "\n")
    clean_text(raw)
  })
)

saveRDS(df, "transcripts.rds")
message("Saved transcripts.rds with ", nrow(df), " rows")
