# Trailarr

Download Trailers for your movies

#### Requirements

requests
beautiful soup

#### How it works

-- Called from custom services/cron job --
Once per week?

1. Get all movies radarr knows about
2. Get all trailer urls from web
3. Add any new urls to db
4. Download any new urls, label broken links
5. Select best video, store result in db
6. Move selected to final destination
7. Clean up temp directory

-- Called from radarr --
On download/upgrade

1. Get all trailer urls from web
2. Add any new urls to db
3. Download any new urls, label broken links
4. Select best video file, store result in db
5. Move selected to final destination
6. Clean up temp dir

-- Called from TUI --
User determined

1. User selects a movie
2. Details of movie and trailer is shown
3. Other options are displayed
4. User selects a new trailer
5. Results stored in db
6. Download and move to final destination
7. Clean up temp dir

Adjust config in TUI?
