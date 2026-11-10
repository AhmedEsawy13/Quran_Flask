/* AudioWorklet for the tajweed check: collects the microphone's mono samples and posts them in blocks of 4096 frames
 * (about 85 ms at 48 kHz) to static/js/tajweed-check.js, which pushes them into a TajweedFormer stream. */
class TajweedCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.block = new Float32Array(4096);
        this.filled = 0;
    }

    process(inputs) {
        const channel = inputs[0] && inputs[0][0];
        if (!channel) return true;
        let offset = 0;
        while (offset < channel.length) {
            const take = Math.min(channel.length - offset, this.block.length - this.filled);
            this.block.set(channel.subarray(offset, offset + take), this.filled);
            this.filled += take;
            offset += take;
            if (this.filled === this.block.length) {
                this.port.postMessage(this.block.slice(0));
                this.filled = 0;
            }
        }
        return true;
    }
}

registerProcessor('tajweed-capture', TajweedCapture);
