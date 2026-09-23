// Minimal ambient types for pngjs@7 (ships no .d.ts, and @types/pngjs is not a dependency).
// Only the surface the fidelity helpers use: PNG.sync.read/write, PNG.bitblt and the RGBA pixel buffer.
declare module "pngjs" {
  export interface PNGOptions {
    width?: number;
    height?: number;
  }
  export class PNG {
    constructor(options?: PNGOptions);
    width: number;
    height: number;
    /** RGBA, 4 bytes/pixel, row-major (stride = width*4). */
    data: Buffer;
    /** Copy a width×height block from src (sx,sy) into dst (dx,dy). */
    static bitblt(src: PNG, dst: PNG, sx: number, sy: number, width: number, height: number, dx: number, dy: number): void;
    static sync: {
      read(buffer: Buffer): PNG;
      write(png: PNG): Buffer;
    };
  }
}
