# Customer-Specific Build Properties

This document explains how the Jenkins pipeline loads customer-specific build properties and sets them as environment variables.

## Overview

The pipeline now reads customer-specific build.properties files and loads all variables as environment variables for use in subsequent stages.

## File Structure

### Required Files
- `CASA-build.properties` - CASA customer build properties
- `Netsuite-build.properties` - Netsuite customer build properties

### File Location
The build properties files should be located at:
- `${BasePath}\CASA-build.properties`
- `${BasePath}\Netsuite-build.properties`

## How It Works

### 1. Customer Selection
The pipeline uses the `customer` parameter to determine which build properties file to load:
- If `customer = "CASA"` → loads `CASA-build.properties`
- If `customer = "Netsuite"` → loads `Netsuite-build.properties`

### 2. File Loading
```groovy
def buildPropsFile = "${BasePath}\\${params.customer}-build.properties"
```

### 3. Property Parsing
The pipeline parses each line in the build properties file:
- Skips comments (lines starting with `#`)
- Skips empty lines
- Parses key-value pairs (format: `key=value`)

### 4. Placeholder Replacement
The pipeline replaces placeholders in property values:
- `%customer%` → actual customer name (CASA or Netsuite)
- `%BasePath%` → actual base path value

### 5. Environment Variable Setting
All parsed properties are stored in `env.BUILD_PROPERTIES` and can be used in subsequent stages.

## Example Build Properties Files

### CASA-build.properties
```properties
# CASA Build Properties
# This file contains build-specific properties for CASA customer

# Version Information
VersionYear=2025
VersionMonth=01
VersionName=CASA-v1.0

# Build Configuration
TargetFrameworkVersion=v4.5.2
ReferenceLibraries=%BasePath%\\ReferenceLibs\\lib
eShopaidDBPath=%BasePath%\\DBObjects\\sql
eShopaidDBSourcePath=%BasePath%\\DBObjects\\sql
IISeShopaidPath=%BasePath%\\CASA\\Build\\IIS_eShopaid
IISHangfirePath=%BasePath%\\CASA\\Build\\IIS_Hangfire
WorkspacePath=%BasePath%\\Workspace
SourceFolder=%BasePath%\\CASA\\Source
TempDBPath=%BasePath%\\TempDBFiles
eShopaidDBUpdatePath=%BasePath%\\CASA\\Build\\sql

# CASA-specific boolean flags
Wondersoft_ShopaidExceptions=true
Wondersoft_Shopaid=true
Wondersoft=true
Wondersoft_ShopaidInterfaces=true
Newtonsoft_Json=true
Wondersoft_Logger=true
Wondersoft_Security_Cryptography=true
Wondersoft_IMWFLibrary=true
Wondersoft_Web_Help_dll=true
Wondersoft_Web_Help2=true
Wondersoft_IMWF_RunnableFactory=true

# Additional CASA-specific properties
CASA_DatabaseName=eShopaid_DB
CASA_ApplicationName=CASA_Application
CASA_ServicePort=8080
CASA_LogLevel=INFO
```

### Netsuite-build.properties
```properties
# Netsuite Build Properties
# This file contains build-specific properties for Netsuite customer

# Version Information
VersionYear=2025
VersionMonth=01
VersionName=Netsuite-v1.0

# Build Configuration
TargetFrameworkVersion=v4.5.2
ReferenceLibraries=%BasePath%\\ReferenceLibs\\lib
NetsuiteDBPath=%BasePath%\\DBObjects\\sql
NetsuiteDBSourcePath=%BasePath%\\DBObjects\\sql
IISNetsuitePath=%BasePath%\\Netsuite\\Build\\IIS_Netsuite
IISHangfirePath=%BasePath%\\Netsuite\\Build\\IIS_Hangfire
WorkspacePath=%BasePath%\\Workspace
SourceFolder=%BasePath%\\Netsuite\\Source
TempDBPath=%BasePath%\\TempDBFiles
NetsuiteDBUpdatePath=%BasePath%\\Netsuite\\Build\\sql

# Netsuite-specific boolean flags
Netsuite_Integration=true
Netsuite_WebServices=true
Netsuite_Logger=true
Netsuite_Security=true
Netsuite_IMWFLibrary=true
Netsuite_Web_Help_dll=true
Netsuite_Web_Help2=true
Netsuite_IMWF_RunnableFactory=true

# Additional Netsuite-specific properties
Netsuite_DatabaseName=Netsuite_DB
Netsuite_ApplicationName=Netsuite_Application
Netsuite_ServicePort=8081
Netsuite_LogLevel=DEBUG
Netsuite_APIEndpoint=https://api.netsuite.com
```

## Usage in Pipeline

### 1. In Build Stage
The properties are loaded using `withEnv`:
```groovy
stage('Build') {
    steps {
        script {
            def propertiesArray = env.BUILD_PROPERTIES.split('\n')
            def propertiesList = propertiesArray.toList()
            
            withEnv(propertiesList) {
                // All properties are now available as environment variables
                // e.g., ${VersionYear}, ${eShopaidDBPath}, ${Wondersoft_Shopaid}, etc.
                
                msbuild(
                    msBuildFile: "${WorkspacePath}\\Integration_CASA\\Build.xml",
                    msBuildName: 'Integration-msbuild',
                    cmdLineArgs: '',
                    buildVariablesAsProperties: false,
                    continueOnBuildFailure: false,
                    unstableIfWarnings: false,
                    doNotUseChcpCommand: false
                )
            }
        }
    }
}
```

### 2. In Other Stages
Properties can be accessed using `${env.PROPERTY_NAME}`:
```groovy
echo "Version: ${env.VersionName}"
echo "Database Path: ${env.eShopaidDBPath}"
echo "Service Port: ${env.CASA_ServicePort}"
```

## Adding New Customers

### Step 1: Create Build Properties File
Create a new file: `{CustomerName}-build.properties`

### Step 2: Add Properties
Add all customer-specific properties to the file:
```properties
# {CustomerName} Build Properties
VersionYear=2025
VersionMonth=01
VersionName={CustomerName}-v1.0
# ... other properties
```

### Step 3: Update Choice Parameter
Add the new customer to the choice parameter in Jenkinsfile:
```groovy
choice(
    name: 'customer',
    choices: ['CASA', 'Netsuite', 'NewCustomer'],
    description: 'Select customer to build for'
)
```

## Benefits

1. **Customer-Specific**: Each customer has their own build properties
2. **Flexible**: Easy to add new properties for each customer
3. **Maintainable**: All properties in one file per customer
4. **Environment Variables**: All properties available as environment variables
5. **Placeholder Support**: Dynamic values based on customer and base path
6. **Error Handling**: Clear error messages if files are missing

## Error Handling

- **File Not Found**: Pipeline fails with clear error message if build properties file doesn't exist
- **Invalid Format**: Properties with invalid format are skipped
- **Missing Values**: Properties without values are skipped

## Example Output

When the pipeline runs for CASA customer, it will output:
```
Loaded CASA build properties:
VersionYear=2025
VersionMonth=01
VersionName=CASA-v1.0
TargetFrameworkVersion=v4.5.2
ReferenceLibraries=D:\JenkinsNew\IntegrationJenkins\ReferenceLibs\lib
eShopaidDBPath=D:\JenkinsNew\IntegrationJenkins\DBObjects\sql
...

Found property: VersionYear = 2025
Found property: VersionMonth = 01
Found property: VersionName = CASA-v1.0
...
```

This approach provides a clean, maintainable way to handle customer-specific build properties and environment variables.
