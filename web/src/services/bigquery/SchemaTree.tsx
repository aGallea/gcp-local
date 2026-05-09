import type { BqFieldInfo } from "../../api/types";

import styles from "./bigquery.module.css";

interface Props {
  schema: BqFieldInfo[];
}

export function SchemaTree({ schema }: Props) {
  return (
    <table className={styles.compactTable}>
      <thead>
        <tr>
          <th>Field</th>
          <th>Type</th>
          <th>Mode</th>
        </tr>
      </thead>
      <tbody>{schema.map((f) => renderField(f, ""))}</tbody>
    </table>
  );
}

function renderField(field: BqFieldInfo, prefix: string) {
  const path = prefix ? `${prefix}.${field.name}` : field.name;
  const rows = [
    <tr key={path}>
      <td style={{ paddingLeft: 12 + prefix.split(".").filter(Boolean).length * 16 }}>
        {field.name}
      </td>
      <td>{field.type}</td>
      <td>{field.mode}</td>
    </tr>,
  ];
  if (field.fields) {
    for (const sub of field.fields) {
      rows.push(...renderField(sub, path));
    }
  }
  return rows;
}
