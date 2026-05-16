# PhotoManager
> Suite for Intelligent Photo Management

## Included Tools

- cais
- delview
- mover
- imagetags
- timeInject


## Workflow
If you want to update your library with new phots procede as follows:

### 1. Select Files
Select all new files. If you are unsure wether your files are alreay in the database you can scan the `cais scan` and afterward extract all new files with `mover extract` to a temp dir `.temp_store`.

### 2. Update File Names

- 1. move your files to `G:\Projects\PhotoManager\data\input`
- 2. activate Ollama 
- 3. run `imagetags`

### 3. (optionally) Inject Time
If you have any files in `G:\Projects\PhotoManager\data\output_notime` you can inject time manually by running `timeInject`

### 4. Move Files
Move all updated files to their target directory in database, for instance `database/2026`

### 5. Update your Database

- 1. Go to `D:\Bilder\database`
- 2. Run `cais scan --perceptual --update`


## Pull from other databases
This section is if you have multiple databases, for example one central and a backup one. 

- 1. Go to the location of your central database
- 2. `cais scan .`
- 3. `cais scan <external db>`
- 4. `cais pull <external db>`

