import iconv from 'iconv-lite';

export type CharacterEncoding = 'utf-8' | 'euc-kr' | 'gbk' | 'gb18030';

export interface RequestProfile {
  headers: Record<string, string>;
  encoding?: CharacterEncoding;
  timeoutMs?: number;
  maxRedirects?: number;
}

export class HttpFetcher {
  private static domainCookieJars = new Map<string, Map<string, string>>();

  /**
   * SSRF protection check: Blocks requests to loopback, link-local, or private IP ranges
   */
  public static isPrivateIp(hostname: string): boolean {
    if (
      hostname === 'localhost' ||
      hostname === '127.0.0.1' ||
      hostname === '0.0.0.0' ||
      hostname === '::1' ||
      hostname.startsWith('10.') ||
      hostname.startsWith('192.168.') ||
      hostname.startsWith('169.254.')
    ) {
      return true;
    }
    const parts = hostname.split('.').map(Number);
    if (parts.length === 4 && parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) {
      return true;
    }
    return false;
  }

  /**
   * Fetches URL with custom profile, cookie jar, charset decoding, and SSRF security
   */
  public static async fetch(
    targetUrl: string,
    profile: RequestProfile
  ): Promise<{ html: string; statusCode: number; finalUrl: string }> {
    const parsedUrl = new URL(targetUrl);
    if (this.isPrivateIp(parsedUrl.hostname)) {
      throw new Error(`[SSRF Security Error] Refusing to fetch private IP target: ${parsedUrl.hostname}`);
    }

    const domain = parsedUrl.hostname;
    if (!this.domainCookieJars.has(domain)) {
      this.domainCookieJars.set(domain, new Map());
    }
    const jar = this.domainCookieJars.get(domain)!;
    const cookieHeader = Array.from(jar.entries())
      .map(([k, v]) => `${k}=${v}`)
      .join('; ');

    const headers: Record<string, string> = {
      'User-Agent':
        profile.headers?.['User-Agent'] ||
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      'Accept-Language':
        profile.headers?.['Accept-Language'] || 'en-US,en;q=0.9,ko;q=0.8,ja;q=0.7,zh;q=0.6',
      Referer: profile.headers?.['Referer'] || `${parsedUrl.protocol}//${parsedUrl.host}/`,
      ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      ...profile.headers,
    };

    const controller = new AbortController();
    const timeoutMs = profile.timeoutMs || 8000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const resp = await fetch(targetUrl, {
        headers,
        signal: controller.signal,
      });
      clearTimeout(timer);

      // Extract and save Set-Cookie headers for session continuity
      const setCookie = resp.headers.get('set-cookie');
      if (setCookie) {
        const parts = setCookie.split(';');
        const [kv] = parts;
        if (kv && kv.includes('=')) {
          const [k, v] = kv.split('=');
          jar.set(k.trim(), v.trim());
        }
      }

      const arrayBuffer = await resp.arrayBuffer();
      const buffer = Buffer.from(arrayBuffer);

      let encoding: CharacterEncoding = profile.encoding || 'utf-8';
      const contentType = resp.headers.get('content-type') || '';
      if (contentType.toLowerCase().includes('euc-kr')) {
        encoding = 'euc-kr';
      } else if (contentType.toLowerCase().includes('gbk') || contentType.toLowerCase().includes('gb18030')) {
        encoding = 'gbk';
      }

      let html = '';
      if (encoding === 'utf-8') {
        html = buffer.toString('utf-8');
      } else {
        html = iconv.decode(buffer, encoding);
      }

      return {
        html,
        statusCode: resp.status,
        finalUrl: resp.url || targetUrl,
      };
    } catch (err: any) {
      clearTimeout(timer);
      throw new Error(`HttpFetcher execution error for ${targetUrl}: ${err.message}`);
    }
  }

  /**
   * Clears cookie jar for a given domain or all domains
   */
  public static clearCookies(domain?: string): void {
    if (domain) {
      this.domainCookieJars.delete(domain);
    } else {
      this.domainCookieJars.clear();
    }
  }
}
