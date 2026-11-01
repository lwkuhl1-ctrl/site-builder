# Site Builder

Makes a full local-business website (same SEO/AEO setup as kljunkremoval.com) from a form.

## Use it
1. Double-click **Start Site Builder.bat**. The builder opens at http://localhost:8840.
2. Fill in the business: name, industry, services (`Name | description`, one per line), towns, phone, hours, logo, colors.
   After you upload a logo, click a color it found and then click a color box to use it.
3. Click **Build Website**, then **Preview site** to click around it, then **Download zip**.
4. Follow `sites/<business>/LAUNCH-CHECKLIST.md` (Cloudflare Pages upload, domain, Search Console, Google Business Profile).

Saved businesses show on the left. Click one, change anything, and build again.

## Turn on AI copy and stock photos (one-time setup)
Open PowerShell (Windows key, type `PowerShell`, Enter) and run these two lines with your real keys. Each should say **SUCCESS**.
```
setx ANTHROPIC_API_KEY "sk-ant-your-key"
setx PIXABAY_API_KEY "your-pixabay-key"
```
- Anthropic key: console.anthropic.com, then API Keys. Each site costs about $0.50–$1.50 the first time. Rebuilds reuse the copy already written, so only new services or towns cost anything (tick "Rewrite all copy" to pay for a full rewrite).
- Pixabay key (free): log in at pixabay.com, open pixabay.com/api/docs and scroll to "Parameters"; your key is shown next to `key`. Photos are free for commercial use, no credit needed. (Pexels also works if you already have a key, `setx PEXELS_API_KEY ...`, but Pexels paused new keys.)

Close the builder window and start it again. The top-right badge should say **AI copy: ready · Stock photos: on**.

## Photos
- Per service: add the owner's photo in section 6. Empty services get a matching Pixabay stock photo (or a brand-color panel if stock is off). The builder tags each one as their photo, stock photo or brand panel.
- Gallery: up to 12 past-job photos, shown on the home page and spread across town pages. Real photos only; stock never goes in the gallery.
- Any size works, 4K included. Photos get shrunk and saved as fast WebP files in 3 sizes.

## Lead form types
Section 7 picks how customers reach the business: **Quote request**, **Book appointment** (day + time), **Contact / consultation**, or **Call-only** (no form, big Call/Text buttons). All buttons and wording across the site change to match.

## What every site gets
- Home, Services + one page per service, Service Areas + one page per town, Pricing (if prices are entered), About, FAQ, Contact, Get a Quote, Privacy Policy, Terms, 404
- Answer-first intros, fact grids, FAQ blocks and "Last updated" dates (what AI answer engines quote)
- JSON-LD: LocalBusiness, Service, BreadcrumbList, FAQPage, WebPage
- `llms.txt`, `sitemap.xml`, `robots.txt`, canonical and Open Graph tags, share image, favicon, clean URLs
- Mobile call/text/quote bar and a quote form (Web3Forms key = emailed leads; with no key, the form opens the visitor's text app)

## Folders
- `clients/<slug>/`: saved inputs, logo and photos
- `.stock-cache/`: downloaded stock photos (so a service keeps the same photo on rebuilds)
- `sites/<slug>/site/`: the website (upload this), plus the zip and `LAUNCH-CHECKLIST.md`
- `sitebuilder/`: the generator (`generator.py` pages/schema, `writer.py` copy, `theme.css` design)
