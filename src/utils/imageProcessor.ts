import fs from 'fs';
import path from 'path';
import sharp from 'sharp';
import crypto from 'crypto';

const UPLOADS_DIR = path.resolve(process.cwd(), 'public', 'uploads', 'covers');

export async function processAndSaveCoverImage(imageUrl: string, seriesId?: number | string): Promise<string> {
  if (!imageUrl || !imageUrl.startsWith('http')) {
    return imageUrl || 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80';
  }

  try {
    if (!fs.existsSync(UPLOADS_DIR)) {
      fs.mkdirSync(UPLOADS_DIR, { recursive: true });
    }

    const resp = await fetch(imageUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      },
      signal: AbortSignal.timeout(8000),
    });

    if (!resp.ok) {
      console.warn(`[Image Processor] Failed to download cover image from ${imageUrl}, status: ${resp.status}`);
      return imageUrl;
    }

    const arrayBuffer = await resp.arrayBuffer();
    const inputBuffer = Buffer.from(arrayBuffer);

    // Verify magic bytes & re-encode to WebP
    const filename = seriesId ? `cover_${seriesId}.webp` : `cover_${crypto.createHash('md5').update(imageUrl).digest('hex').substring(0, 10)}.webp`;
    const outputPath = path.resolve(UPLOADS_DIR, filename);

    await sharp(inputBuffer)
      .resize({ width: 800, height: 1200, fit: 'cover', withoutEnlargement: true })
      .webp({ quality: 85 })
      .toFile(outputPath);

    return `/uploads/covers/${filename}`;
  } catch (err) {
    console.warn('[Image Processor] Error processing cover image:', err);
    return imageUrl;
  }
}
