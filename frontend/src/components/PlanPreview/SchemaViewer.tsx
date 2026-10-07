import React, { useState } from 'react';
import {
  Database,
  FileJson,
  Key,
  ChevronRight,
  ChevronDown,
  Layers,
  Tag,
  Hash,
  Link,
  ShieldCheck,
  FolderTree,
} from 'lucide-react';
import { DatabaseSchema, TableDefinition, CollectionDefinition } from '../../types';
import { Tooltip } from '../ui/Tooltip';
import { Chip } from '../ui/Chip';

export interface SchemaViewerProps {
  database: DatabaseSchema;
}

// Recursive Tree Node for MongoDB JSON Schema
interface SchemaNodeProps {
  name: string;
  schema: Record<string, any>;
  required?: boolean;
  level?: number;
}

const SchemaTreeNode: React.FC<SchemaNodeProps> = ({
  name,
  schema,
  required = false,
  level = 0,
}) => {
  const [isOpen, setIsOpen] = useState(true);

  if (!schema || typeof schema !== 'object') {
    return null;
  }

  const bsonType = schema.bsonType || schema.type || 'any';
  const properties = schema.properties || {};
  const items = schema.items || null;
  const description = schema.description || '';
  const requiredList: string[] = Array.isArray(schema.required) ? schema.required : [];

  const isContainer =
    (bsonType === 'object' && Object.keys(properties).length > 0) ||
    (bsonType === 'array' && items && items.properties);

  const getTypeBadgeColor = (type: string) => {
    switch (type.toLowerCase()) {
      case 'string':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
      case 'int':
      case 'number':
      case 'double':
        return 'bg-blue-500/10 text-blue-400 border-blue-500/30';
      case 'bool':
      case 'boolean':
        return 'bg-purple-500/10 text-purple-400 border-purple-500/30';
      case 'object':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
      case 'array':
        return 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30';
      case 'date':
      case 'timestamp':
        return 'bg-rose-500/10 text-rose-400 border-rose-500/30';
      default:
        return 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30';
    }
  };

  return (
    <div className="font-mono text-xs select-text">
      <div
        className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-surface/60 transition-colors ${
          level > 0 ? 'ml-4 border-l border-line/50 pl-2' : ''
        }`}
      >
        {isContainer ? (
          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className="p-0.5 text-ink-tertiary hover:text-ink-primary transition-colors"
          >
            {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-3.5 inline-block text-ink-tertiary">•</span>
        )}

        <span className="font-semibold text-ink-primary">{name}</span>

        <span
          className={`text-[10px] px-1.5 py-0.5 rounded border uppercase tracking-wider font-medium ${getTypeBadgeColor(
            bsonType
          )}`}
        >
          {bsonType}
          {bsonType === 'array' && items?.bsonType ? ` <${items.bsonType}>` : ''}
        </span>

        {required && (
          <span className="text-[10px] font-bold text-amber-400 bg-amber-500/10 px-1 rounded border border-amber-500/20">
            REQ
          </span>
        )}

        {description && (
          <span className="text-ink-tertiary text-[11px] truncate max-w-xs font-sans italic">
            — {description}
          </span>
        )}
      </div>

      {isOpen && isContainer && (
        <div className="space-y-0.5">
          {bsonType === 'object' &&
            Object.entries(properties).map(([childKey, childSchema]: [string, any]) => (
              <SchemaTreeNode
                key={childKey}
                name={childKey}
                schema={childSchema}
                required={requiredList.includes(childKey)}
                level={level + 1}
              />
            ))}

          {bsonType === 'array' && items && items.properties && (
            <div className="ml-4 border-l border-cyan-500/30 pl-2">
              <div className="text-[10px] text-cyan-400 py-1 italic font-sans">
                Array Item Schema (Object):
              </div>
              {Object.entries(items.properties).map(([childKey, childSchema]: [string, any]) => (
                <SchemaTreeNode
                  key={childKey}
                  name={childKey}
                  schema={childSchema}
                  required={Array.isArray(items.required) && items.required.includes(childKey)}
                  level={level + 1}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const SchemaViewer: React.FC<SchemaViewerProps> = ({ database }) => {
  const isNoSQL = database.provider?.toLowerCase() === 'mongodb' || (database.collections && database.collections.length > 0);
  const tables = database.tables || [];
  const collections = database.collections || [];

  return (
    <div className="space-y-6">
      {/* Header Info Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs bg-elevated/40 p-3.5 rounded-xl border border-line">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-brand/10 border border-brand/20 text-brand">
            {isNoSQL ? <FileJson className="h-5 w-5" /> : <Database className="h-5 w-5" />}
          </div>
          <div>
            <div className="text-ink-secondary text-[11px]">Database Architecture</div>
            <div className="text-ink-primary font-bold text-sm flex items-center gap-2">
              <span>{database.database_name || database.name || 'app_db'}</span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-brand/12 text-brand font-mono uppercase font-semibold">
                {database.provider}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4 text-ink-secondary">
          {isNoSQL ? (
            <span>
              Collections: <strong className="text-ink-primary font-mono">{collections.length}</strong>
            </span>
          ) : (
            <span>
              Tables: <strong className="text-ink-primary font-mono">{tables.length}</strong>
            </span>
          )}
          {database.extensions && database.extensions.length > 0 && (
            <span>
              Extensions:{' '}
              <strong className="text-ink-primary font-mono">{database.extensions.join(', ')}</strong>
            </span>
          )}
        </div>
      </div>

      {/* RENDER MONGODB DOCUMENT SCHEMAS */}
      {isNoSQL && (
        <div className="space-y-4">
          {collections.map((col, idx) => {
            const schemaProps = col.document_schema?.properties || {};
            const embeddedList = col.embedded_documents || [];
            const indexList = col.indexes || [];

            return (
              <div
                key={idx}
                className="bg-elevated border border-line rounded-xl overflow-hidden shadow-sm"
              >
                {/* Collection Header */}
                <div className="px-4 py-3 bg-surface border-b border-line flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <FolderTree className="h-4 w-4 text-emerald-400" />
                    <span className="font-mono font-bold text-sm text-ink-primary">{col.name}</span>
                    <span className="text-[11px] text-ink-tertiary">
                      ({Object.keys(schemaProps).length} top-level fields)
                    </span>
                  </div>

                  {embeddedList.length > 0 && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-ink-tertiary uppercase">Embedded:</span>
                      {embeddedList.map((emb, eIdx) => (
                        <span
                          key={eIdx}
                          className="text-[10px] font-mono px-2 py-0.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 rounded"
                        >
                          {emb}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {col.description && (
                  <p className="px-4 py-2 text-xs text-ink-secondary border-b border-line/40 italic bg-base/30">
                    {col.description}
                  </p>
                )}

                {/* Document JSON Schema Tree */}
                <div className="p-4 bg-base/50">
                  <div className="text-[10px] uppercase font-bold text-ink-tertiary mb-2 flex items-center gap-1.5">
                    <ShieldCheck className="h-3.5 w-3.5 text-brand" />
                    <span>MongoDB $jsonSchema Document Validator</span>
                  </div>

                  <div className="p-3 bg-elevated/70 rounded-lg border border-line/70 space-y-1">
                    {col.document_schema && Object.keys(schemaProps).length > 0 ? (
                      Object.entries(schemaProps).map(([fieldName, fieldSchema]: [string, any]) => (
                        <SchemaTreeNode
                          key={fieldName}
                          name={fieldName}
                          schema={fieldSchema}
                          required={
                            Array.isArray(col.document_schema?.required) &&
                            col.document_schema.required.includes(fieldName)
                          }
                          level={0}
                        />
                      ))
                    ) : (
                      <div className="text-xs text-ink-tertiary font-mono italic">
                        No validation schema constraints specified. Free-form document structure.
                      </div>
                    )}
                  </div>
                </div>

                {/* Collection Indexes Footer */}
                {indexList.length > 0 && (
                  <div className="px-4 py-2.5 bg-surface/50 border-t border-line text-[11px] flex items-center gap-3">
                    <Hash className="h-3.5 w-3.5 text-brand" />
                    <span className="text-ink-tertiary font-medium">Indexes:</span>
                    <div className="flex flex-wrap gap-2">
                      {indexList.map((idxItem, iIdx) => {
                        let label = JSON.stringify(idxItem);
                        let isUnique = false;
                        if (typeof idxItem === 'object') {
                          isUnique = Boolean(idxItem.unique);
                          if ('fields' in idxItem) {
                            label = idxItem.fields.join(', ');
                          }
                        }
                        return (
                          <span
                            key={iIdx}
                            className="font-mono bg-base px-2 py-0.5 rounded border border-line text-ink-primary flex items-center gap-1"
                          >
                            <span>{label}</span>
                            {isUnique && <span className="text-[9px] text-amber-400 font-bold">UNIQUE</span>}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* RENDER RELATIONAL TABLES (POSTGRESQL & MYSQL) */}
      {!isNoSQL && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {tables.map((tbl, tIdx) => (
            <div key={tIdx} className="bg-elevated border border-line rounded-xl overflow-hidden shadow-sm">
              <div className="px-4 py-2.5 bg-surface border-b border-line flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-brand" />
                  <span className="font-mono font-bold text-xs text-ink-primary">{tbl.name}</span>
                </div>
                <span className="text-[11px] text-ink-tertiary">{tbl.columns.length} columns</span>
              </div>

              {tbl.description && (
                <p className="px-4 py-2 text-[11px] text-ink-secondary border-b border-line/50 italic">
                  {tbl.description}
                </p>
              )}

              <table className="w-full text-xs text-left">
                <thead className="text-[10px] uppercase tracking-wider text-ink-tertiary bg-base/50 border-b border-line/60">
                  <tr>
                    <th className="px-4 py-2 font-medium">Column</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Constraints</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/40 font-mono text-[11px]">
                  {tbl.columns.map((col, cIdx) => (
                    <tr key={cIdx} className="hover:bg-surface/40">
                      <td className="px-4 py-2 text-ink-primary flex items-center gap-1.5 font-semibold">
                        {col.primary_key && (
                          <Tooltip content="Primary Key">
                            <Key className="h-3 w-3 text-amber-400" />
                          </Tooltip>
                        )}
                        <span>{col.name}</span>
                      </td>
                      <td className="px-4 py-2 text-brand font-medium">{col.data_type}</td>
                      <td className="px-4 py-2 text-ink-secondary space-x-1.5">
                        {col.primary_key && <span className="text-amber-400 font-semibold">PK</span>}
                        {!col.nullable && !col.primary_key && (
                          <span className="text-ink-primary font-medium">NOT NULL</span>
                        )}
                        {col.unique && !col.primary_key && <span className="text-sky-400">UNIQUE</span>}
                        {col.references && <span className="text-emerald-400">FK({col.references})</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Foreign Keys & Indexes Footer */}
              {((tbl.indexes && tbl.indexes.length > 0) || (tbl.foreign_keys && tbl.foreign_keys.length > 0)) && (
                <div className="px-4 py-2 bg-surface/40 border-t border-line text-[10px] text-ink-tertiary space-y-1">
                  {tbl.foreign_keys &&
                    tbl.foreign_keys.map((fk, fIdx) => (
                      <div key={fIdx} className="flex items-center gap-1 text-emerald-400/90 truncate">
                        <Link className="h-3 w-3 inline" />
                        <span>
                          {fk.columns.join(', ')} → {fk.ref_table}({fk.ref_columns.join(', ')})
                        </span>
                      </div>
                    ))}
                  {tbl.indexes &&
                    tbl.indexes.map((idx, iIdx) => (
                      <div key={iIdx} className="flex items-center gap-1 text-ink-tertiary truncate">
                        <Hash className="h-3 w-3 inline" />
                        <span>
                          {idx.name} ({idx.columns.join(', ')})
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SchemaViewer;
