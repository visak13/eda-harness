// Minimal ambient types for pngjs@7 (ships no .d.ts, and @types/pngjs is not a dependency).
// Only the surface the fidelity helpers use: PNG.sync.read/write and the RGBA pixel buffer.
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
    static sync: {
      read(buffer: Buffer): PNG;
      write(png: PNG): Buffer;
    };
  }
}
