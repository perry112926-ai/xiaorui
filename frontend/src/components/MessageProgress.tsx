import React from 'react';
export function MessageProgress({text,stream}:{text:string;stream?:string}){
 return <div className="message-progress"><span role="status" className="message-progress-label"><span className="reply-dot" aria-hidden="true"/>{text||'正在回复'}</span>{stream&&<p className="message-text">{stream}</p>}</div>;
}
