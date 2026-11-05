import React from 'react';

type Props={title:string;description?:string;eyebrow?:string;status?:string;icon?:'meal'|'place'|'route'|'document'|'pin'};
const paths={
 meal:<><path d="M7 3v7m-3-7v5a3 3 0 0 0 6 0V3M7 11v10M18 3c-3 3-3 7 0 9v9m0-18v9"/></>,
 place:<><path d="M3 10h18l-2-6H5l-2 6ZM5 10v10h14V10M9 20v-6h6v6"/><path d="M3 10c0 3 4 3 4 0 0 3 3 3 5 0 1 3 5 3 5 0 0 3 4 3 4 0"/></>,
 route:<><circle cx="6" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M6 7v7a4 4 0 0 0 4 4h6M18 17v-7a4 4 0 0 0-4-4h-3"/></>,
 document:<><path d="M7 3h8l4 4v14H5V3h2Zm8 0v5h4M9 12h6m-6 4h6"/></>,
 pin:<><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
};
export function CardHeading({title,description,eyebrow,status,icon='document'}:Props){
 return <div className="card-heading"><span className="card-heading-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{paths[icon]}</svg></span><div className="card-heading-copy">{eyebrow&&<span className="card-heading-eyebrow">{eyebrow}</span>}<h3>{title}</h3>{description&&<p>{description}</p>}</div>{status&&<span className="card-heading-status">{status}</span>}</div>;
}
