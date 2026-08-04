# Disastorous

Real-time disaster and crime risk, built on free public data.

Live at: https://onlinehackathon.vercel.app

## Inspiration

On a recent road trip, one of our team members drove straight into a massive wildfire without knowing it was even happening. They hadn't checked the news that morning; why would they, they were just driving. By the time they hit smoke and highway closures, they had no choice but to pull off and book a hotel for the night. That "surprise" cost them $500 they hadn't budgeted for, and the worst part was that it was completely avoidable. The fire had already been burning and reported for hours before they got anywhere near it. The information existed. They just had no way to see it before it became their problem.

That's the gap Disastorous is built to close. Nobody should have to eat a $500 hotel bill and lose a night of their trip because a wildfire, a storm, or an earthquake wasn't on their radar. The data to prevent that already exists, scattered across NASA's disaster feeds, USGS earthquake reports, and local news. It just needed to be pulled into one place a person could actually check before they leave.

## What it does

Disastorous is two connected tools built on free, public data:

- **Local Danger Search** — enter a city and a radius, and get a danger score out of 100 built from recent news about disasters and crime near that place, cross-checked against confirmed live hazards (active NASA-tracked natural events and recent earthquakes). Every article and event behind the score is listed and linked, so nothing is a black box.
- **Global Danger View** — a live world map of every currently active NASA-tracked disaster and significant recent earthquake, with an overall read on how calm or active the planet is right now, plus a quick "check a place" lookup for anywhere on Earth.

Layered on top: a Nextdoor-style community feature where signed-in users post a geotagged report with a photo about what they're seeing nearby, visible to anyone searching that area, and a chat assistant that answers questions grounded specifically in the articles and hazards your search actually pulled up.

## How we built it

The frontend is deliberately simple: vanilla HTML/CSS/JS with MapLibre GL for mapping, no framework or build step, deployed as a static site on Vercel. All the underlying data comes from free public sources: a global news index for disaster/crime search, NASA's Earth Observatory Natural Event Tracker, the USGS earthquake feed, and OpenStreetMap/Nominatim for geocoding. A small Vercel serverless function proxies chat requests to an LLM, keeping the API key server-side and out of the browser entirely. The community layer runs on Supabase (Postgres + Auth + Storage) with Row Level Security, so users can only ever edit or delete their own posts. The color system was validated against colorblind accessibility rather than picked by eye.

## Challenges we ran into

- The news API enforces a strict rate limit, so disaster/crime searches had to be serialized with retry logic instead of fired in parallel.
- Free-text place names are more ambiguous than expected — "Fremont" exists in California, Colorado, Nebraska, and Ohio, and our first version was quietly mixing in disaster news from the wrong Fremont. Fixed by requiring the geocoded state/region alongside the city name in every news query.
- A CSS specificity bug made a form field impossible to actually hide via JavaScript, even though it *looked* correctly hidden on first load, a good reminder those aren't the same thing.
- Transactional email was a bigger time sink than any single feature: the default sender has a testing-only rate limit, and even a real SMTP provider's sandbox only delivers to the developer's own inbox until a domain is verified. We switched auth from magic-link email to email/password specifically to remove that dependency from login entirely.
- The chat assistant occasionally returned no reply, traced to reading the first block of the model's response instead of specifically locating the text block.

## Accomplishments that we're proud of

- Both tools run entirely on free public data, with every score, marker, and claim traceable back to a real, clickable source.
- The danger score and the chat assistant are both explicitly honest about their limits, since news search can't return exact incident coordinates, we show a clearly-labeled approximate marker instead of faking a precise pin.
- A real, working community reporting system with authentication, photo uploads, and proper access control, not a mockup.
- A live, deployed, working product at the end of the week, not a slide deck.

## What we learned

- Free public data is both more powerful and messier than it looks; disambiguating a place name mattered more to the final product than any single flashy feature.
- Being upfront about what a tool doesn't know builds more trust than faking precision it doesn't have.
- The "simple" parts of a product, like login and transactional email, are often the most deceptively time-consuming.

## What's next for Disastorous

- Verify a real sending domain so email-dependent features work for any user.
- Alerts when a new hazard appears near a place you've searched or saved.
- Bring the chat assistant to Global View, not just Local Search.
- A moderation layer for community reports as usage grows.

## Built with

HTML, CSS, JavaScript, MapLibre GL JS, GDELT, NASA EONET, USGS Earthquake API, OpenStreetMap, Nominatim, Anthropic Claude API, Esri World Imagery, OpenFreeMap, Vercel, Vercel Serverless Functions, Node.js, Supabase, Supabase Auth, Supabase Storage, PostgreSQL, Row Level Security, Git, GitHub
