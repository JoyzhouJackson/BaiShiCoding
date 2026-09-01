interface SectionHeadingProps {
  index: string
  kicker: string
  title: string
  description: string
}

export default function SectionHeading({ index, kicker, title, description }: SectionHeadingProps) {
  return (
    <div className="section-heading">
      <div className="section-index">{index}</div>
      <div>
        <span className="eyebrow">{kicker}</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  )
}
