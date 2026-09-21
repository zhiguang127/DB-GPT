import React from 'react';
// The mock answer uses only paragraphs, bullet points and emphasis. Avoid pulling
// the app's network-capable rich-artifact renderer into the offline attachment.
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part);
}
export default function Markdown({ children }: { children: string }) {
  return <>{children.split('\n\n').map((block, index) => block.startsWith('- ') ? <ul key={index} className='my-3 list-disc pl-5 space-y-1'>{block.split('\n').map((line, item) => <li key={item}>{inline(line.replace(/^- /, ''))}</li>)}</ul> : <p key={index} className='my-2'>{inline(block)}</p>)}</>;
}
