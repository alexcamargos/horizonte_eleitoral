# Migracoes

Os arquivos SQL sao executados em ordem lexicografica em PostgreSQL. Eles sao
append-only: uma alteracao de esquema deve adicionar uma nova migracao, nunca
editar uma migracao ja aplicada. A primeira migracao estabelece o contrato de
auditoria para artefatos brutos, tentativas de ingestao, parser runs, lineage e
snapshots.
