import { ParserSpec } from './types';

export const SOURCE_PARSER_SPECS: Record<string, ParserSpec> = {
  baozimh: {
    version: 1,
    sourceId: 'baozimh',
    name: 'Baozi Manga (包子漫畫)',
    urlPatterns: {
      series: 'https://www.baozimh.com/comic/<slug>',
      chapter: 'https://www.baozimh.com/user/page_direct?comic_id=<slug>&section_slot=0&chapter_slot=<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: 'a[href*="chapter"], .chapter-list a, #chapter-items a',
        fields: {
          number: { selector: 'span, text', attr: 'text' },
          title: { selector: 'span, text', attr: 'text' },
          url: { selector: 'a', attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'img.comic-contain, img[data-src], .comic-contain img',
        attr: 'data-src',
      },
    },
  },

  wujinmh: {
    version: 1,
    sourceId: 'wujinmh',
    name: 'Wujin Manga (無盡漫畫)',
    urlPatterns: {
      series: 'https://www.wujinmh.com/manhua/<id>.html',
      chapter: 'https://www.wujinmh.com/chapter/<id>.html',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '#chapter-list a, .chapter-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'img[data-original], #cp_img img',
        attr: 'data-original',
      },
    },
  },

  yueman1: {
    version: 1,
    sourceId: 'yueman1',
    name: 'YueMan Mobile (閱漫畫)',
    urlPatterns: {
      series: 'https://m.yueman1.cc/manhua/<id>',
      chapter: 'https://m.yueman1.cc/manhua/<id>/<ch>.html',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15',
        'Accept-Language': 'zh-CN,zh;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.chapter-list a, #chlist a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: '.reader-img-box img',
        attr: 'data-src',
      },
    },
  },

  kuaikanmanhua: {
    version: 1,
    sourceId: 'kuaikanmanhua',
    name: 'Kuaikan Manhua (快看漫畫)',
    urlPatterns: {
      series: 'https://www.kuaikanmanhua.com/web/topic/<id>/',
      chapter: 'https://www.kuaikanmanhua.com/web/comic/<id>/',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.TopicList .item a, .chapter-item a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
      flags: { loginRequired: '.login-wall-modal' },
    },
    chapterPage: {
      images: {
        selector: 'img.kuaikan-img, .comic-image img',
        attr: 'data-src',
      },
    },
  },

  mkzhan: {
    version: 1,
    sourceId: 'mkzhan',
    name: 'MKZhan (漫客棧)',
    urlPatterns: {
      series: 'https://www.mkzhan.com/<id>/',
      chapter: 'https://www.mkzhan.com/<id>/<ch>.html',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.chapter__list a, #chapter-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'img.lazy-read, .rd-article__pic img',
        attr: 'data-src',
      },
    },
  },

  tonarinoyj: {
    version: 1,
    sourceId: 'tonarinoyj',
    name: 'Tonari no Young Jump (となりのヤングジャンプ)',
    urlPatterns: {
      series: 'https://tonarinoyj.jp/episode/<id>',
      chapter: 'https://tonarinoyj.jp/episode/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ja-JP,ja;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.sub-title-item a, .episode-header-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'viewer_config' },
    },
    chapterPage: {
      images: {
        selector: 'img.js-page-image',
        attr: 'data-src',
      },
    },
  },

  senmanga: {
    version: 1,
    sourceId: 'senmanga',
    name: 'SenManga Raw',
    urlPatterns: {
      series: 'https://raw.senmanga.com/<slug>',
      chapter: 'https://raw.senmanga.com/<slug>/<chapter>/',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.element a, ul.chapter-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'img.picture, .reader img',
        attr: 'src',
      },
    },
  },

  comicdays: {
    version: 1,
    sourceId: 'comicdays',
    name: 'Comic Days (コミックDAYS)',
    urlPatterns: {
      series: 'https://comic-days.com/episode/<id>',
      chapter: 'https://comic-days.com/episode/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ja-JP,ja;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      stateSource: { kind: 'next_data', jsonPath: 'props.pageProps' },
      chapterList: {
        selector: '.episode-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
    },
    chapterPage: {
      images: {
        selector: 'img.js-page-image',
        attr: 'data-src',
      },
    },
  },

  mangaz: {
    version: 1,
    sourceId: 'mangaz',
    name: 'MangaZ (マンガ図書館Z)',
    urlPatterns: {
      series: 'https://www.mangaz.com/title/<id>/',
      chapter: 'https://www.mangaz.com/chapter/<id>/',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.chapter-list a, #ch-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: '#viewer img',
        attr: 'src',
      },
    },
  },

  comicwalker: {
    version: 1,
    sourceId: 'comicwalker',
    name: 'Comic Walker (KADOKAWA)',
    urlPatterns: {
      series: 'https://comic-walker.com/contents/detail/<id>/',
      chapter: 'https://comic-walker.com/viewer/?cid=<cid>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      stateSource: { kind: 'next_data' },
      chapterList: {
        selector: '#detail-episode-list a, .episode-item a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
    },
    chapterPage: {
      images: {
        selector: '#viewer img',
        attr: 'data-src',
      },
    },
  },

  sundaywebry: {
    version: 1,
    sourceId: 'sundaywebry',
    name: 'Sunday Webry (サンデーうぇぶり)',
    urlPatterns: {
      series: 'https://www.sunday-webry.com/episode/<id>',
      chapter: 'https://www.sunday-webry.com/episode/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '.episode-item a, .series-episode-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'img.js-page-image',
        attr: 'data-src',
      },
    },
  },

  pocketshonen: {
    version: 1,
    sourceId: 'pocketshonen',
    name: 'Pocket Shonen Magazine',
    urlPatterns: {
      series: 'https://pocket.shonenmagazine.com/episode/<id>',
      chapter: 'https://pocket.shonenmagazine.com/episode/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      stateSource: { kind: 'next_data' },
      chapterList: {
        selector: '.series-episode-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
    },
    chapterPage: {
      images: {
        selector: 'img.js-page-image',
        attr: 'data-src',
      },
    },
  },

  shonenjumpplus: {
    version: 1,
    sourceId: 'shonenjumpplus',
    name: 'Shonen Jump+ (少年ジャンプ＋)',
    urlPatterns: {
      series: 'https://shonenjumpplus.com/episode/<id>',
      chapter: 'https://shonenjumpplus.com/episode/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      stateSource: { kind: 'next_data' },
      chapterList: {
        selector: '.series-episode-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
    },
    chapterPage: {
      images: {
        selector: 'img.js-page-image',
        attr: 'data-src',
      },
    },
  },

  naver: {
    version: 1,
    sourceId: 'naver',
    name: 'Naver Webtoon (네이버 웹툰)',
    urlPatterns: {
      series: 'https://comic.naver.com/webtoon/list?titleId=<id>',
      chapter: 'https://comic.naver.com/webtoon/detail?titleId=<id>&no=<ch>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: 'td.title a, ul.EpisodeListList__episode_list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: 'div.wt_viewer img, .ComicViewer__viewer img',
        attr: 'src',
        skipFirstImage: true,
      },
    },
  },

  rawkuma: {
    version: 1,
    sourceId: 'rawkuma',
    name: 'Rawkuma (WordPress Madara)',
    urlPatterns: {
      series: 'https://rawkuma.com/manga/<slug>/',
      chapter: 'https://rawkuma.com/<slug>-chapter-<ch>/',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      encoding: 'utf-8',
    },
    seriesPage: {
      chapterList: {
        selector: '#chapterlist a, ul.main.version-chap a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: '#readerarea img',
        attr: 'data-src',
      },
    },
  },

  wfwf505: {
    version: 1,
    sourceId: 'wfwf505',
    name: 'WFWF505 Korean Raw',
    urlPatterns: {
      series: 'https://wfwf505.com/comic/<id>',
      chapter: 'https://wfwf505.com/viewer/<id>',
    },
    requestProfile: {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
      },
      encoding: 'euc-kr',
    },
    seriesPage: {
      chapterList: {
        selector: '.list-body a, .chapter-list a',
        fields: {
          number: { attr: 'text' },
          title: { attr: 'text' },
          url: { attr: 'href' },
        },
      },
      stateSource: { kind: 'none' },
    },
    chapterPage: {
      images: {
        selector: '.view-padding img',
        attr: 'src',
      },
    },
  },
};
