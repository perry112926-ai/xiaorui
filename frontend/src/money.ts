/** Monetary inputs are safe integer cents. Never round a malformed amount. */
export function formatCents(value:number):string {
 if(!Number.isSafeInteger(value))throw new TypeError('Amount must be safe integer cents');
 const digits=String(Math.abs(value)).padStart(3,'0');
 return `${value<0?'-':''}${digits.slice(0,-2)}.${digits.slice(-2)}`;
}
