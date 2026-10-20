/* Runs only after the user clicks the microphone and permits audio capture. */
class XiaoxiRecorder extends AudioWorkletProcessor {
 constructor(){super();this.samples=new Float32Array(2048);this.used=0;this.recording=true;this.port.onmessage=e=>{if(e.data==='stop'){this.flush();this.recording=false;this.port.postMessage({stopped:true});}};}
 flush(){if(this.used){const samples=this.samples.slice(0,this.used);this.port.postMessage({samples},[samples.buffer]);this.used=0;}}
 process(inputs){const channel=inputs[0]?.[0];if(this.recording&&channel)for(const sample of channel){this.samples[this.used++]=sample;if(this.used===this.samples.length)this.flush();}return true;}
}
registerProcessor('xiaoxi-recorder',XiaoxiRecorder);
