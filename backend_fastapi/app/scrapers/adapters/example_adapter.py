from ..base_scraper import BaseScraper


class ExampleMangaScraper(BaseScraper):
    """
    Adapter for example-manga.com.
    Most logic is handled by BaseScraper if dynamic configs are used.
    Adapter can override specific methods if the site requires custom logic
    (e.g., API calls instead of HTML parsing).
    """

    def __init__(self):
        super().__init__(domain="example-manga.com", delay=2)

    # Example of overriding if a site needs special logic
    # def scrape_manga(self, url: str) -> Dict[str, Any]:
    #     # custom logic here
    #     return super().scrape_manga(url)
