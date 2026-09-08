import styles from "./PageHeader.module.css";

// Shared page title block: Georgia 38px (design §4.2 type scale). Route pages are stubs in
// this story; G2/G3 fill their bodies. The <h1> is what the fidelity spec measures.
export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }): React.JSX.Element {
  return (
    <header className={styles.head}>
      <h1 className={styles.title}>{title}</h1>
      {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
    </header>
  );
}

export function Placeholder({ story }: { story: string }): React.JSX.Element {
  return <p className={styles.placeholder}>This view is delivered in {story}.</p>;
}
