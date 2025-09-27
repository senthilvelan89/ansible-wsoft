pipeline {
    agent any 
    parameters {
        choice(
            name: 'customer',
            choices: ['CASA', 'Netsuite'],
            description: 'Select customer to build for'
        )
        string(
            name: 'release_tag',
            defaultValue: 'trunk',
            description: 'Enter the SVN tag/branch name (e.g., trunk, v1.0, v2.1, etc.)'
        )
        string(
            name: 'BasePath',
            defaultValue: 'D:\\JenkinsNew\\IntegrationJenkins',
            description: 'Base path where all the required files are stored.'
        )
    }   
    
    stages {
        stage('Validate Tag') {
            steps {
                script {
                    withCredentials([usernamePassword(credentialsId: 'svn_user', usernameVariable: 'SVN_USERNAME', passwordVariable: 'SVN_PASSWORD')]) {
                        // Validate that the tag exists
                        def tagExists = bat(
                            script: "svn info svn://repo.wondersoft.in/eshopaid_web/Tags_Integration_QC/${params.release_tag} --username ${SVN_USERNAME} --password ${SVN_PASSWORD} --non-interactive",
                            returnStatus: true
                        )
                        
                        if (tagExists != 0) {
                            error "SVN tag '${params.release_tag}' does not exist or is not accessible. Please check the tag name and try again."
                        }
                        
                        echo "✓ Validated SVN tag: ${params.release_tag}"
                    }
                }
            }
        }
        
        stage('Checkout') {
            steps {
                script {
                    withCredentials([usernamePassword(credentialsId: 'svn_user', usernameVariable: 'SVN_USERNAME', passwordVariable: 'SVN_PASSWORD')]) {
                        // First, checkout the CIFile repository to get the configuration
                        bat '''
                            svn checkout svn://repo.wondersoft.in/eshopaid_web/CIFile %BasePath%\\CIFile --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                        '''
                        
                        // Read the unified checkout configuration from CIFile
                        def configFile = "${BasePath}\\CIFile\\checkout-config.properties"
                        if (!fileExists(configFile)) {
                            error "Configuration file not found: ${configFile}. Please ensure checkout-config.properties exists in the CIFile repository."
                        }
                        
                        def configContent = readFile(file: configFile)
                        echo "Found unified checkout configuration:"
                        echo configContent
                        
                        // Use switch case to handle different customers and their specific SVN repositories
                        switch(params.customer) {
                            case 'CASA':
                                echo "Processing CASA customer checkout..."
                                
                                // CASA-specific SVN checkouts
                                bat """
                                    svn checkout svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/SQL/eShopaid_DB %BasePath%\\DBObjects\\sql --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/CICD/Jenkins/Workspace %BasePath%\\Workspace --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/FWL/LoyaltyVendors/CASA %BasePath%\\CASA\\Source\\Loyalty --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/IMWF/Lib/CustomizedRunnables/CASARunnables %BasePath%\\CASA\\Source\\Runnables --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn export svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/build.properties %BasePath%\\build.properties --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive --force
                                """
                                break
                                
                            case 'Netsuite':
                                echo "Processing Netsuite customer checkout..."
                                
                                // Netsuite-specific SVN checkouts
                                bat """
                                    svn checkout svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/SQL/Netsuite_DB %BasePath%\\DBObjects\\sql --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/CICD/Jenkins/Workspace %BasePath%\\Workspace --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/Integration/Netsuite %BasePath%\\Netsuite\\Source\\Integration --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn checkout svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/IMWF/Lib/CustomizedRunnables/NetsuiteRunnables %BasePath%\\Netsuite\\Source\\Runnables --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive
                                """
                                
                                bat """
                                    svn export svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/build.properties %BasePath%\\build.properties --username %SVN_USERNAME% --password %SVN_PASSWORD% --non-interactive --force
                                """
                                break
                                
                            default:
                                error "Unsupported customer: ${params.customer}. Supported customers are: CASA, Netsuite"
                                break
                        }
                    }
                }
            }
        }
        
        stage('Load Properties') {
            steps {
                script {
                    // Load customer-specific build.properties file
                    def buildPropsFile = "${BasePath}\\${params.customer}-build.properties"
                    if (!fileExists(buildPropsFile)) {
                        error "Build properties file not found: ${buildPropsFile}. Please ensure ${params.customer}-build.properties exists."
                    }
                    
                    def buildPropsContent = bat(
                        script: "type \"${buildPropsFile}\"",
                        returnStdout: true
                    ).trim()
                    
                    echo "Loaded ${params.customer} build properties:"
                    echo buildPropsContent
                    
                    // Parse properties and set them as environment variables
                    def propertiesList = []
                    buildPropsContent.split('\n').each { line ->
                        if (line.contains('=') && !line.startsWith('#')) {
                            def parts = line.split('=', 2)
                            if (parts.length == 2) {
                                def key = parts[0].trim()
                                def value = parts[1].trim()
                                
                                // Replace placeholders in values
                                def actualValue = value
                                    .replace('%customer%', params.customer)
                                    .replace('%BasePath%', BasePath)
                                
                                propertiesList.add("${key}=${actualValue}")
                                echo "Found property: ${key} = ${actualValue}"
                            }
                        }
                    }
                    
                    // Store properties for use in next stage
                    env.BUILD_PROPERTIES = propertiesList.join('\n')
                }
            }
        }
        
        stage('Build') {
            steps {
                script {
                    // Parse the stored properties and use withEnv to set them
                    def propertiesArray = env.BUILD_PROPERTIES.split('\n')
                    def propertiesList = propertiesArray.toList()
                    
                    withEnv(propertiesList) {
                        // MSBuild step with environment variables
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
        
        stage('Copy Artifacts') {
            steps {
                script {
                    switch(params.customer) {
                        case 'CASA':
                            echo "Copying CASA build artifacts..."
                            bat 'xcopy /s /Y %BasePath%\\CASA\\Build\\* %WORKSPACE%\\Build\\'
                            break
                            
                        case 'Netsuite':
                            echo "Copying Netsuite build artifacts..."
                            bat 'xcopy /s /Y %BasePath%\\Netsuite\\Build\\* %WORKSPACE%\\Build\\'
                            break
                            
                        default:
                            error "Unsupported customer: ${params.customer}. Supported customers are: CASA, Netsuite"
                            break
                    }
                }
            }
        }
        
        stage('Upload to S3') {
            steps {
                script {
                    s3Upload(
                        bucket: "cicd-wspipeline/${params.customer}/${params.customer}-QC-Tags/${env.VersionYear}/${env.VersionMonth}/${env.VersionName}",
                        file: "Build/",
                        includePathPattern: "**/*",
                        storageClass: "STANDARD",
                        region: "ap-south-1",
                        noUploadOnFailure: false,
                        uploadFromSlave: false,
                        managedArtifacts: false,
                        useServerSideEncryption: false,
                        flatten: false,
                        gzipFiles: true,
                        showDirectlyInBrowser: false,
                        keepForever: false
                    )
                }
            }
        }
    }
    
    post {
        always {
            // Cleanup workspace
            cleanWs()
        }
        
        success {
            script {
                def emailBody = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>${env.JOB_NAME} - Build # ${env.BUILD_NUMBER} - ${currentBuild.result}</title>
<style>
    body {
      font-family: Arial, sans-serif;
      font-size: 14px;
      color: #333;
      line-height: 1.6;
    }
    a {
      color: #1a73e8;
      text-decoration: none;
    }
    .highlight {
      font-weight: bold;
      color: #2e7d32;
    }
</style>
</head>
<body>
<p>Dear Team,</p>
 
  <p>The artifacts are ready for Testing and are located in the below link:</p>
 
  <ul>
<li>
<a href="https://s3.ap-south-1.amazonaws.com/cicd-wspipeline/${params.customer}/${params.customer}-QC-Tags/${params.release_tag}" target="_blank">
        Download Artifacts
</a>
</li>

</ul>
 
  <p>
    📄 You can check the console output at:<br>
<a href="${env.BUILD_URL}" target="_blank">
      Jenkins Build Console Output
</a>
<p class="highlight">🟢 ${env.JOB_NAME} - Build # ${env.BUILD_NUMBER} - ${currentBuild.result}:</p>
 
</p>
 
  <p>Best regards,<br>Your DevOps Team</p>
</body>
</html>
                """
                
                emailext(
                    subject: "${params.customer}-Past-${params.release_tag}",
                    body: emailBody,
                    to: "kannan@wondersoft.com,nethaji.vaithilingam@wondersoft.com,benita.s@wondersoft.com",
                    from: "crmreports@wondersoft.com",
                    mimeType: "text/html"
                )
            }
        }
        
        failure {
            emailext(
                subject: "${env.JOB_NAME} - Build # ${env.BUILD_NUMBER} - ${currentBuild.result}",
                body: "${env.JOB_NAME} - Build # ${env.BUILD_NUMBER} - ${currentBuild.result}:\n\nCheck console output at ${env.BUILD_URL} to view the results.",
                to: "kannan@wondersoft.com,nethaji.vaithilingam@wondersoft.com,benita.s@wondersoft.com",
                from: "crmreports@wondersoft.com"
            )
        }
    }
}
