-- Contract test inputs for sqlite_core. These statements define the behavior
-- a faithful port should reproduce. Ports do NOT have to compile/pass; this
-- file documents the expected semantics so the judge can score completeness.
CREATE TABLE users (uid INTEGER, uname TEXT);
CREATE TABLE posts (pid INTEGER, uid INTEGER, body TEXT);
INSERT INTO users VALUES (1, 'ada');
INSERT INTO users VALUES (2, 'grace');
INSERT INTO users VALUES (3, 'linus');
INSERT INTO posts VALUES (10, 1, 'hello');
INSERT INTO posts VALUES (11, 2, 'world');
INSERT INTO posts VALUES (12, 1, 'again');

-- expected: 3 | linus \n 2 | grace
SELECT * FROM users WHERE uid > 1 ORDER BY uid DESC;

-- expected: ada | hello \n ada | again \n grace | world
SELECT users.uname, posts.body FROM users INNER JOIN posts ON users.uid = posts.uid;

-- expected (projection): ada \n grace \n linus
SELECT uname FROM users ORDER BY uname ASC;
