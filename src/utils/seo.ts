export interface SeoOptions {
  title?: string;
  description?: string;
  imageUrl?: string;
  type?: 'website' | 'article' | 'book';
  canonicalUrl?: string;
  jsonLd?: Record<string, any>;
}

export function updatePageSeo(options: SeoOptions): void {
  const defaultTitle = 'Manga Reader - Read & Translate Manga Online';
  const defaultDesc =
    'Read, translate, and manage manga, manhwa and manhua online. Browse genres, bookmark favorite series, and enjoy AI OCR speech bubble overlays.';
  const defaultImage = '/logo512.png';

  const title = options.title ? `${options.title} - Manga Reader` : defaultTitle;
  const description = options.description || defaultDesc;
  const imageUrl = options.imageUrl || defaultImage;
  const currentUrl = options.canonicalUrl || (typeof window !== 'undefined' ? window.location.href : '');

  // 1. Title
  document.title = title;

  // 2. Meta Description
  let metaDesc = document.querySelector('meta[name="description"]');
  if (!metaDesc) {
    metaDesc = document.createElement('meta');
    metaDesc.setAttribute('name', 'description');
    document.head.appendChild(metaDesc);
  }
  metaDesc.setAttribute('content', description);

  // 3. OpenGraph Tags
  const ogTags: Record<string, string> = {
    'og:title': title,
    'og:description': description,
    'og:image': imageUrl,
    'og:type': options.type || 'website',
    'og:url': currentUrl,
  };

  Object.entries(ogTags).forEach(([prop, val]) => {
    let tag = document.querySelector(`meta[property="${prop}"]`);
    if (!tag) {
      tag = document.createElement('meta');
      tag.setAttribute('property', prop);
      document.head.appendChild(tag);
    }
    tag.setAttribute('content', val);
  });

  // 4. Twitter Cards
  const twitterTags: Record<string, string> = {
    'twitter:card': 'summary_large_image',
    'twitter:title': title,
    'twitter:description': description,
    'twitter:image': imageUrl,
  };

  Object.entries(twitterTags).forEach(([name, val]) => {
    let tag = document.querySelector(`meta[name="${name}"]`);
    if (!tag) {
      tag = document.createElement('meta');
      tag.setAttribute('name', name);
      document.head.appendChild(tag);
    }
    tag.setAttribute('content', val);
  });

  // 5. Schema.org JSON-LD Structured Data
  let script = document.getElementById('schema-jsonld') as HTMLScriptElement | null;
  if (!script) {
    script = document.createElement('script');
    script.id = 'schema-jsonld';
    script.type = 'application/ld+json';
    document.head.appendChild(script);
  }

  const jsonLdData = options.jsonLd || {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    name: 'Manga Reader',
    applicationCategory: 'EntertainmentApplication',
    operatingSystem: 'All',
    description,
    url: currentUrl,
  };

  script.textContent = JSON.stringify(jsonLdData);
}
