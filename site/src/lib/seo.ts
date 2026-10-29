/* Whether search engines may index the site. Kept out at launch, as the family's
   other pages are, until the owner says the page is meant to be found. Flipping
   this to true lets every page be indexed and puts the sitemap line back in
   robots.txt; a page that passes `noindex` to the layout stays out either way. */
export const INDEXABLE = false;
