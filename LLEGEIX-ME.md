# Gestor de Correus

Programa d'escriptori per netejar i organitzar comptes de correu per IMAP
(servidors amb Roundcube i Gmail). Tots els canvis s'apliquen directament al servidor.

## Descarregar (sense Python)
Ves a **Releases → «Gestor de Correus (última versió)»** i baixa `GestorCorreus.exe`.
És un únic fitxer portable per a Windows 10/11: no s'instal·la res i no cal Python.

- Els comptes es desen a la carpeta `GestorCorreus_dades`, al costat de l'`.exe`
  (si la carpeta no es pot escriure, es fa servir `%APPDATA%\GestorCorreus`).
- Les contrasenyes desades es xifren amb l'usuari de Windows. Si portes l'`.exe`
  a un altre ordinador, els comptes hi són però et demanarà la contrasenya.
- Windows SmartScreen pot avisar la primera vegada (l'exe no està signat):
  «Més informació» → «Executa igualment».

Cada `push` a `main` torna a compilar l'`.exe` automàticament (GitHub Actions).

## Què fa
- **Comptes**: tants com vulguis, Roundcube (IMAP/SMTP) o Gmail. Pots desar la
  contrasenya o que te la demani cada cop.
- **Correus**: arbre de carpetes plegable a l'esquerra (amb cercador). Cerca per
  nom o adreça del remitent, selecciona'ls tots i elimina'ls o mou-los. Pots
  arrossegar correus damunt de qualsevol carpeta de l'arbre. Tecla Supr = eliminar.
- **Remitents**: qui t'envia més correus, per adreça o per domini sencer
  (p. ex. tot `infojobs.net`), i elimina'ls o mou-los tots d'un cop.
- **Carpetes**: arbre amb subcarpetes; crea, crea subcarpetes, reanomena,
  elimina i buida la paperera.
- **Informació**: espai lliure del compte (o «Il·limitat» si el servidor no té límit).

## Desenvolupament
- `Iniciar.bat` executa la versió Python (cal Python 3.10+).
- `python tests/test_backend.py` passa les proves del motor amb un IMAP simulat.
