export type ProviderKind = "ocr" | "translation" | "ai" | "inpainting" | "detection";

export interface ProviderMetadata {
  id: string;
  name?: string;
  label?: string;
  description?: string;
  requiresKey?: boolean;
  allowsUrl?: boolean;
  allowsModel?: boolean;
  source?: string;
  defaultUrl?: string;
  defaultModel?: string;
}

export interface OverlayBox {
  id?: string;
  x: number;
  y: number;
  w?: number;
  h?: number;
  width?: number;
  height?: number;
  text?: string;
  confidence?: number;
  [key: string]: any;
}

export interface OcrRunOptions {
  language?: string;
  [key: string]: any;
}

export interface OcrRunResult {
  boxes: OverlayBox[];
  warnings?: string[];
  metadata?: Record<string, any>;
}

export interface OcrProvider {
  id: string;
  label: string;
  description?: string;
  run: (image: any, options?: OcrRunOptions) => Promise<OcrRunResult>;
  isAvailable?: () => boolean;
}
